from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from mcp.server.fastmcp import FastMCP
from pydantic import Field

try:
    from .knowledge_store import KnowledgeStore
except ImportError:
    from knowledge_store import KnowledgeStore


BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

mcp = FastMCP("SmartHomeV2Strict")
store = KnowledgeStore(KNOWLEDGE_DIR)


@mcp.tool()
def set_lighting(
    room: Optional[str] = Field(None, description="Target room."),
    fixture: Optional[Union[str, List[str]]] = Field(None, description="One or more lights."),
    preset: Optional[str] = Field(None, description="Lighting preset or color."),
    intensite: Optional[int] = Field(None, ge=1, le=10, description="Intensity from 1 to 10."),
) -> Dict[str, Any]:
    """
    Turn on or update lights only.
    Use for room-only commands ('allume [room]') and room+preset.
    Never use this tool for TV, speakers, fans, or heating devices.
    Missing argument means argument is absent and must not be inferred.
    """
    return {
        "tool": "set_lighting",
        "status": "accepted",
        "scope": room or "all",
        "args": {k: v for k, v in {"room": room, "fixture": fixture, "preset": preset, "intensite": intensite}.items() if v is not None},
    }


@mcp.tool()
def turn_off_light(
    room: Optional[str] = Field(None, description="Target room."),
    fixture: Optional[Union[str, List[str]]] = Field(None, description="One or more lights."),
) -> Dict[str, Any]:
    """
    Turn off lights only.
    Use for room-only off-command ('eteins [room]').
    args:{} means all lights in all rooms.
    Never use this tool for non-light devices.
    """
    return {
        "tool": "turn_off_light",
        "status": "accepted",
        "scope": room or "all",
        "args": {k: v for k, v in {"room": room, "fixture": fixture}.items() if v is not None},
    }


@mcp.tool()
def set_temperature(
    temperature: int = Field(..., ge=5, le=35, description="Target temperature in celsius."),
    room: Optional[str] = Field(None, description="Target room."),
) -> Dict[str, Any]:
    """
    Set climate temperature.
    Requires an explicit numeric target. Never guess or infer room if not clearly stated.
    """
    return {
        "tool": "set_temperature",
        "status": "accepted",
        "scope": room or "all",
        "args": {k: v for k, v in {"temperature": temperature, "room": room}.items() if v is not None},
    }


@mcp.tool()
def set_humidity(
    humidity: int = Field(..., ge=0, le=100, description="Target humidity percentage."),
    room: Optional[str] = Field(None, description="Target room."),
) -> Dict[str, Any]:
    """Set humidity target only."""
    return {
        "tool": "set_humidity",
        "status": "accepted",
        "scope": room or "all",
        "args": {k: v for k, v in {"humidity": humidity, "room": room}.items() if v is not None},
    }


@mcp.tool()
def get_sensor_data(
    type: Literal["temperature", "humidite", "qualite_air", "co2"] = Field(..., description="Sensor type."),
    room: Optional[str] = Field(None, description="Target room."),
) -> Dict[str, Any]:
    """
    Read sensors only.
    If no room is provided, scope is global (all available rooms).
    """
    return {
        "tool": "get_sensor_data",
        "status": "accepted",
        "scope": room or "all",
        "args": {k: v for k, v in {"type": type, "room": room}.items() if v is not None},
    }


@mcp.tool()
def turn_on_devices(
    devices: List[str] = Field(..., description="Device names, not lights."),
    rooms: Optional[List[str]] = Field(None, description="Target rooms."),
) -> Dict[str, Any]:
    """
    Turn on non-light devices only. Requires explicit device name.
    Never use for lights or room-only commands (use set_lighting instead).
    """
    return {
        "tool": "turn_on_devices",
        "status": "accepted",
        "scope": rooms or ["all"],
        "args": {k: v for k, v in {"devices": devices, "rooms": rooms}.items() if v is not None},
    }


@mcp.tool()
def turn_off_devices(
    devices: Optional[List[str]] = Field(None, description="Device names to turn off."),
    rooms: Optional[List[str]] = Field(None, description="Target rooms."),
) -> Dict[str, Any]:
    """
    Turn off non-light devices only. Requires explicit device name.
    args:{} means all non-light devices everywhere.
    """
    return {
        "tool": "turn_off_devices",
        "status": "accepted",
        "scope": rooms or ["all"],
        "args": {k: v for k, v in {"devices": devices, "rooms": rooms}.items() if v is not None},
    }


@mcp.tool()
def set_global_preset(
    preset: str = Field(..., description="Global preset name."),
) -> Dict[str, Any]:
    """
    Apply one global preset to the entire home.
    Only for house-wide modes. Not for single rooms.
    """
    return {
        "tool": "set_global_preset",
        "status": "accepted",
        "scope": "all",
        "args": {"preset": preset},
    }


@mcp.tool()
def set_reminder(
    message: str = Field(..., description="Reminder text."),
    date: Optional[str] = Field(None, description="Natural language datetime."),
) -> Dict[str, Any]:
    """Create reminder only. Keep date absent if not mentioned."""
    return {
        "tool": "set_reminder",
        "status": "accepted",
        "args": {k: v for k, v in {"message": message, "date": date}.items() if v is not None},
    }


@mcp.tool()
def step_back() -> Dict[str, Any]:
    """Undo latest action only. Use for annule/cancel/undo. NOT for reminder."""
    return {"tool": "step_back", "status": "accepted", "args": {}}


@mcp.tool()
def do_nothing(
    reason: Optional[str] = Field(None, description="Optional reason for no action."),
) -> Dict[str, Any]:
    """
    No-op tool for out-of-scope, unclear, jokes, or no numeric values.
    Also used when a command has no action verb.
    Always include reason in args.
    """
    payload: Dict[str, Any] = {"tool": "do_nothing", "status": "accepted", "args": {}}
    if reason:
        payload["reason"] = reason
    return payload


@mcp.tool()
def upsert_home_entity(
    entity_type: Literal["room", "device", "preset", "sensor", "alias", "rule"] = Field(
        ..., description="Entity type to create or update."
    ),
    entity_id: str = Field(..., description="Entity identifier."),
    data: Dict[str, Any] = Field(..., description="Entity payload."),
    scope: Optional[str] = Field(
        None,
        description="Optional namespace. For example: room for device, global/lighting for preset.",
    ),
) -> Dict[str, Any]:
    """
    Create or update one knowledge entity.
    This tool writes to versioned knowledge files.
    """
    return store.upsert_home_entity(
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
        scope=scope,
    )


if __name__ == "__main__":
    mcp.run()

