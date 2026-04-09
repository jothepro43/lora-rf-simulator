"""Network link model for mesh topology planning."""

from sqlalchemy import Column, Integer, Float, String, Boolean, ForeignKey
from models.database import Base


class NetworkLink(Base):
    __tablename__ = "network_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node1_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    node2_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)

    # Computed/cached values (filled after analysis)
    distance_km = Column(Float, default=0)
    path_loss_db = Column(Float, default=0)
    is_los = Column(Boolean, default=False)
    clearance_pct = Column(Float, default=0)
    link_margin_db = Column(Float, default=0)
    status = Column(String, default="unknown")  # excellent/good/viable/marginal/blocked/unknown

    notes = Column(String, default="")
