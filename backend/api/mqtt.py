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


# In-memory config store (would be persisted in Phase 3)
_mqtt_config = MqttConfig()


@router.get("/config")
def get_mqtt_config():
    """Get current MQTT configuration."""
    return {
        "server_url": _mqtt_config.server_url,
        "port": _mqtt_config.port,
        "topic": _mqtt_config.topic,
        "username": _mqtt_config.username,
        "enabled": _mqtt_config.enabled,
        "status": "not_implemented",
        "message": "MQTT integration coming in Phase 3",
    }


@router.post("/config")
def update_mqtt_config(config: MqttConfig):
    """Update MQTT configuration (stub - saves in memory only)."""
    global _mqtt_config
    _mqtt_config = config
    return {
        "status": "saved",
        "message": "Configuration saved (MQTT connection not yet implemented)",
        "config": {
            "server_url": config.server_url,
            "port": config.port,
            "topic": config.topic,
            "enabled": config.enabled,
        },
    }


@router.get("/status")
def mqtt_status():
    """Get MQTT connection status (stub)."""
    return {
        "connected": False,
        "status": "not_implemented",
        "message": "MQTT integration coming in Phase 3",
    }
