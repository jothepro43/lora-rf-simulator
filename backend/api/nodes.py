"""Node CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from models.database import get_db
from models.node import Node

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class NodeCreate(BaseModel):
    name: str = "Site"
    lat: float
    lon: float
    height_agl: float = 10.0
    device_preset: str = "rak4631"
    antenna_preset: str = "rak_pcb_patch"
    cable_type: str = "ideal"
    cable_length_m: float = 0.0
    connectors: int = 0
    frequency_mhz: float = 915.0
    tx_power_dbm: float = 22.0
    rx_sensitivity_dbm: float = -148.0
    antenna_gain_dbi: float = 2.0
    role: str = "CLIENT"
    channel_preset: str = "LONG_FAST"
    notes: str = ""


class NodeUpdate(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    height_agl: Optional[float] = None
    device_preset: Optional[str] = None
    antenna_preset: Optional[str] = None
    cable_type: Optional[str] = None
    cable_length_m: Optional[float] = None
    connectors: Optional[int] = None
    frequency_mhz: Optional[float] = None
    tx_power_dbm: Optional[float] = None
    rx_sensitivity_dbm: Optional[float] = None
    antenna_gain_dbi: Optional[float] = None
    role: Optional[str] = None
    channel_preset: Optional[str] = None
    notes: Optional[str] = None


class NodeResponse(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    height_agl: float
    device_preset: str
    antenna_preset: str
    cable_type: str
    cable_length_m: float
    connectors: int
    frequency_mhz: float
    tx_power_dbm: float
    rx_sensitivity_dbm: float
    antenna_gain_dbi: float
    role: str
    channel_preset: str
    notes: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[NodeResponse])
def list_nodes(db: Session = Depends(get_db)):
    return db.query(Node).all()


@router.post("", response_model=NodeResponse)
def create_node(node: NodeCreate, db: Session = Depends(get_db)):
    db_node = Node(**node.model_dump())
    db.add(db_node)
    db.commit()
    db.refresh(db_node)
    return db_node


@router.get("/export", response_model=list[NodeResponse])
def export_nodes(db: Session = Depends(get_db)):
    return db.query(Node).all()


@router.post("/import")
def import_nodes(nodes: list[NodeCreate], db: Session = Depends(get_db)):
    created = []
    for node_data in nodes:
        db_node = Node(**node_data.model_dump())
        db.add(db_node)
        created.append(db_node)
    db.commit()
    return {"detail": f"Imported {len(created)} nodes"}


@router.get("/{node_id}", response_model=NodeResponse)
def get_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/{node_id}", response_model=NodeResponse)
def update_node(node_id: int, update: NodeUpdate, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    db.commit()
    db.refresh(node)
    return node


@router.delete("/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    db.delete(node)
    db.commit()
    return {"detail": "Node deleted", "id": node_id}
