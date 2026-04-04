"""MQTT integration stub endpoints (Phase 3 placeholder)."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/mqtt", tags=["mqtt"])


class MqttConfig(BaseModel):
    server_url: str = ""
    port: int = 1883
    topic: str = "meshtastic/#"
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = False


class MqttStatus(BaseModel):
    connected: bool = False
    server_url: str = ""
    messages_received: int = 0
    last_message_at: Optional[str] = None


_config = MqttConfig()


@router.get("/config")
def get_mqtt_config() -> MqttConfig:
    """Get current MQTT configuration."""
    return _config


@router.post("/config")
def update_mqtt_config(config: MqttConfig) -> MqttConfig:
    """Update MQTT configuration (stub — does not connect yet)."""
    global _config
    _config = config
    return _config


@router.get("/status")
def get_mqtt_status() -> MqttStatus:
    """Get MQTT connection status (stub — always disconnected)."""
    return MqttStatus(server_url=_config.server_url)


@router.post("/connect")
def connect_mqtt():
    """Connect to MQTT broker (stub — not implemented yet)."""
    return {"status": "not_implemented", "message": "MQTT integration coming in Phase 3"}


@router.post("/disconnect")
def disconnect_mqtt():
    """Disconnect from MQTT broker (stub — not implemented yet)."""
    return {"status": "not_implemented", "message": "MQTT integration coming in Phase 3"}
