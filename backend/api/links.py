"""Network link CRUD + analysis endpoints."""

import math
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models.database import get_db
from models.link import NetworkLink
from models.node import Node

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/links", tags=["links"])


class LinkCreate(BaseModel):
    node1_id: int
    node2_id: int
    notes: str = ""


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


@router.post("/analyze")
def analyze_all_links(db: Session = Depends(get_db)):
    from services.los_profile import compute_los_profile

    links = db.query(NetworkLink).all()
    results = []
    for link in links:
        n1 = db.query(Node).filter(Node.id == link.node1_id).first()
        n2 = db.query(Node).filter(Node.id == link.node2_id).first()
        if not n1 or not n2:
            continue
        try:
            profile = compute_los_profile(
                tx_lat=n1.lat, tx_lon=n1.lon, tx_height_m=n1.height_agl,
                rx_lat=n2.lat, rx_lon=n2.lon, rx_height_m=n2.height_agl,
                frequency_mhz=n1.frequency_mhz, num_points=200,
            )
            path_loss = profile.get("path_loss", {}).get("total_path_loss_db", 0)
            received = n1.tx_power_dbm + n1.antenna_gain_dbi + n2.antenna_gain_dbi - path_loss
            margin = received - n2.rx_sensitivity_dbm

            if margin > 30:
                status = "excellent"
            elif margin > 20:
                status = "good"
            elif margin > 10:
                status = "viable"
            elif margin > 0:
                status = "marginal"
            else:
                status = "blocked"

            link.distance_km = round(profile.get("total_distance_m", 0) / 1000, 2)
            link.path_loss_db = round(path_loss, 1)
            link.is_los = profile.get("is_los", False)
            link.clearance_pct = profile.get("clearance_pct", 0)
            link.link_margin_db = round(margin, 1)
            link.status = status
        except Exception as e:
            logger.error("Failed to analyze link %d: %s", link.id, e)
            link.status = "unknown"

        results.append({
            "link_id": link.id,
            "node1": n1.name, "node2": n2.name,
            "distance_km": link.distance_km,
            "margin_db": link.link_margin_db,
            "status": link.status,
            "is_los": link.is_los,
        })

    db.commit()
    return results


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
