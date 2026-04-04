from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime
from .database import Base


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, default="Site")
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    height_agl = Column(Float, default=10.0)
    device_preset = Column(String, default="rak4631")
    antenna_preset = Column(String, default="rak_pcb_patch")
    cable_type = Column(String, default="ideal")
    cable_length_m = Column(Float, default=0.0)
    connectors = Column(Integer, default=0)
    frequency_mhz = Column(Float, default=915.0)
    tx_power_dbm = Column(Float, default=22.0)
    rx_sensitivity_dbm = Column(Float, default=-148.0)
    antenna_gain_dbi = Column(Float, default=2.0)
    antenna_azimuth_deg = Column(Float, default=0.0)
    antenna_tilt_deg = Column(Float, default=0.0)
    role = Column(String, default="CLIENT")
    channel_preset = Column(String, default="LONG_FAST")
    notes = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
