"""Network link CRUD + analysis + multi-hop pathfinding endpoints."""

import math
import logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from models.database import get_db
from models.link import NetworkLink
from models.node import Node
from services.routing import EdgeView, NodeView, find_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/links", tags=["links"])


# Match SUPPORTED_PATH_LOSS_MODELS in services.propagation
PathLossModel = Literal["fspl", "fspl_diffraction", "fspl_weather", "full"]
ClutterProfile = Literal[
    "open", "suburban", "urban", "temperate_forest", "dense_forest"
]
PathObjective = Literal["hops", "lowest_total_loss", "best_bottleneck_margin"]


class LinkCreate(BaseModel):
    node1_id: int
    node2_id: int
    notes: str = ""


class AnalyzeOptions(BaseModel):
    """Optional knobs for /analyze. All fields have sensible defaults."""

    model: PathLossModel = "full"
    clutter_profile: ClutterProfile = "open"
    clutter_tree_height_m: Optional[float] = Field(default=None, ge=0)
    clutter_tree_density: Optional[float] = Field(default=None, ge=0, le=1)
    rain_rate_mmh: float = Field(default=0.0, ge=0)
    wet_foliage: bool = False
    ice: bool = False
    num_profile_points: int = Field(default=200, ge=10, le=2000)


@router.get("")
def list_links(db: Session = Depends(get_db)):
    links = db.query(NetworkLink).all()
    result = []
    for link in links:
        n1 = db.query(Node).filter(Node.id == link.node1_id).first()
        n2 = db.query(Node).filter(Node.id == link.node2_id).first()
        d = {c.name: getattr(link, c.name) for c in link.__table__.columns}
        d["node1_name"] = n1.name if n1 else "?"
        d["node2_name"] = n2.name if n2 else "?"
        d["node1_lat"] = n1.lat if n1 else 0
        d["node1_lon"] = n1.lon if n1 else 0
        d["node2_lat"] = n2.lat if n2 else 0
        d["node2_lon"] = n2.lon if n2 else 0
        result.append(d)
    return result


@router.post("")
def create_link(data: LinkCreate, db: Session = Depends(get_db)):
    if data.node1_id == data.node2_id:
        raise HTTPException(400, "Cannot link a node to itself")
    existing = db.query(NetworkLink).filter(
        ((NetworkLink.node1_id == data.node1_id) & (NetworkLink.node2_id == data.node2_id))
        | ((NetworkLink.node1_id == data.node2_id) & (NetworkLink.node2_id == data.node1_id))
    ).first()
    if existing:
        raise HTTPException(400, "Link already exists")
    link = NetworkLink(node1_id=data.node1_id, node2_id=data.node2_id, notes=data.notes)
    db.add(link)
    db.commit()
    db.refresh(link)
    return {c.name: getattr(link, c.name) for c in link.__table__.columns}


@router.delete("/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(NetworkLink).filter(NetworkLink.id == link_id).first()
    if link:
        db.delete(link)
        db.commit()
    return {"ok": True}


@router.delete("")
def clear_all_links(db: Session = Depends(get_db)):
    count = db.query(NetworkLink).delete()
    db.commit()
    return {"deleted": count}


def _classify_margin(margin: float) -> str:
    if margin > 30:
        return "excellent"
    if margin > 20:
        return "good"
    if margin > 10:
        return "viable"
    if margin > 0:
        return "marginal"
    return "blocked"


@router.post("/analyze")
def analyze_all_links(
    options: Optional[AnalyzeOptions] = None,
    db: Session = Depends(get_db),
):
    """Run LoS + path-loss analysis for every link.

    Body is optional; defaults yield FSPL + diffraction + weather (no
    clutter). Pass ``clutter_profile`` etc. to align with coverage-map
    assumptions.
    """
    from services.los_profile import compute_los_profile
    from services.propagation import compute_path_loss
    from services.terrain import reset_missing_tiles, get_missing_tiles

    opts = options or AnalyzeOptions()
    reset_missing_tiles()

    links = db.query(NetworkLink).all()
    results = []
    for link in links:
        n1 = db.query(Node).filter(Node.id == link.node1_id).first()
        n2 = db.query(Node).filter(Node.id == link.node2_id).first()
        if not n1 or not n2:
            continue
        try:
            profile = compute_los_profile(
                lat1=n1.lat, lon1=n1.lon, tx_height_m=n1.height_agl,
                lat2=n2.lat, lon2=n2.lon, rx_height_m=n2.height_agl,
                frequency_mhz=n1.frequency_mhz,
                num_points=opts.num_profile_points,
            )
            path_loss_result = compute_path_loss(
                profile["distances"],
                profile["elevations"],
                n1.height_agl,
                n2.height_agl,
                n1.frequency_mhz,
                model=opts.model,
                rain_rate_mmh=opts.rain_rate_mmh,
                wet_foliage=opts.wet_foliage,
                ice=opts.ice,
                clutter_profile=opts.clutter_profile,
                clutter_tree_height_m=opts.clutter_tree_height_m,
                clutter_tree_density=opts.clutter_tree_density,
            )
            path_loss = path_loss_result.get("total_path_loss_db", 0)
            received = (
                n1.tx_power_dbm + n1.antenna_gain_dbi + n2.antenna_gain_dbi - path_loss
            )
            margin = received - n2.rx_sensitivity_dbm
            status = _classify_margin(margin)

            link.distance_km = round(profile.get("total_distance_m", 0) / 1000, 2)
            link.path_loss_db = round(path_loss, 1)
            link.is_los = profile.get("is_los", False)
            link.clearance_pct = profile.get("clearance_pct", 0)
            link.link_margin_db = round(margin, 1)
            link.status = status
        except Exception as e:
            logger.error("Failed to analyze link %d: %s", link.id, e)
            link.status = "unknown"
            path_loss_result = None

        results.append({
            "link_id": link.id,
            "node1": n1.name, "node2": n2.name,
            "distance_km": link.distance_km,
            "margin_db": link.link_margin_db,
            "status": link.status,
            "is_los": link.is_los,
            "breakdown": path_loss_result,
        })

    db.commit()

    missing = get_missing_tiles()
    return {
        "links": results,
        "data_quality": {
            "missing_srtm_tiles": missing,
            "low_confidence": bool(missing),
        },
    }


@router.post("/auto-discover")
def auto_discover_links(
    max_distance_km: float = Query(50, description="Max distance between nodes"),
    db: Session = Depends(get_db),
):
    nodes = db.query(Node).all()
    created = 0
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            n1, n2 = nodes[i], nodes[j]
            dlat = (n2.lat - n1.lat) * 111
            dlon = (n2.lon - n1.lon) * 111 * math.cos(math.radians(n1.lat))
            dist = math.sqrt(dlat ** 2 + dlon ** 2)
            if dist <= max_distance_km:
                existing = db.query(NetworkLink).filter(
                    ((NetworkLink.node1_id == n1.id) & (NetworkLink.node2_id == n2.id))
                    | ((NetworkLink.node1_id == n2.id) & (NetworkLink.node2_id == n1.id))
                ).first()
                if not existing:
                    db.add(NetworkLink(node1_id=n1.id, node2_id=n2.id))
                    created += 1
    db.commit()
    return {"created": created, "total_nodes": len(nodes)}


# ---------------------------------------------------------------------------
# Multi-hop pathfinding
# ---------------------------------------------------------------------------


class PathRequest(BaseModel):
    source_id: int
    dest_id: int
    objective: PathObjective = "hops"
    max_hops: Optional[int] = Field(default=None, ge=1, le=32)
    min_margin_db: Optional[float] = None
    allow_unanalyzed: bool = False
    allowed_relay_roles: Optional[list[str]] = None


def _node_views(db: Session) -> list[NodeView]:
    return [
        NodeView(id=n.id, name=n.name, role=n.role or "")
        for n in db.query(Node).all()
    ]


def _edge_views(db: Session) -> list[EdgeView]:
    return [
        EdgeView(
            link_id=l.id,
            node_a=l.node1_id,
            node_b=l.node2_id,
            distance_km=l.distance_km or 0.0,
            path_loss_db=l.path_loss_db or 0.0,
            link_margin_db=l.link_margin_db or 0.0,
            status=l.status or "unknown",
            is_los=bool(l.is_los),
        )
        for l in db.query(NetworkLink).all()
    ]


@router.post("/path")
def solve_path(req: PathRequest, db: Session = Depends(get_db)):
    """Find the best multi-hop path from ``source_id`` to ``dest_id``.

    Run ``/api/links/analyze`` first so margins/path-loss are populated.
    """
    if req.source_id == req.dest_id:
        raise HTTPException(400, "source_id and dest_id must differ")

    nodes = _node_views(db)
    edges = _edge_views(db)

    try:
        solution = find_path(
            nodes=nodes,
            edges=edges,
            source_id=req.source_id,
            dest_id=req.dest_id,
            objective=req.objective,
            max_hops=req.max_hops,
            min_margin_db=req.min_margin_db,
            allow_unanalyzed=req.allow_unanalyzed,
            allowed_relay_roles=req.allowed_relay_roles,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if solution is None:
        return {
            "found": False,
            "objective": req.objective,
            "reason": (
                "No usable path found. Run /analyze first or pass "
                "allow_unanalyzed=true to include blocked/unknown edges."
            ),
        }

    node_lookup = {n.id: n for n in db.query(Node).all()}
    return {
        "found": True,
        "objective": solution.objective,
        "hops": solution.hops,
        "total_path_loss_db": solution.total_path_loss_db,
        "total_distance_km": solution.total_distance_km,
        "end_to_end_margin_db": solution.end_to_end_margin_db,
        "bottleneck_link_id": solution.bottleneck_link_id,
        "node_ids": solution.nodes,
        "link_ids": solution.links,
        "node_names": [
            node_lookup[nid].name if nid in node_lookup else f"#{nid}"
            for nid in solution.nodes
        ],
    }
