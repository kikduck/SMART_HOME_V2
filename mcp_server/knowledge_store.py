from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class KnowledgeStore:
    """Single source of truth for versioned home knowledge."""

    def __init__(self, knowledge_dir: Path) -> None:
        self.knowledge_dir = knowledge_dir
        self.home_state_path = knowledge_dir / "home_state.json"
        self.aliases_path = knowledge_dir / "aliases.json"
        self.rules_path = knowledge_dir / "rules.json"

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_current_knowledge(self) -> Dict[str, Any]:
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "home_state": self._read_json(self.home_state_path),
            "aliases": self._read_json(self.aliases_path),
            "rules": self._read_json(self.rules_path),
        }

    def upsert_home_entity(
        self,
        entity_type: str,
        entity_id: str,
        data: Dict[str, Any],
        scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not entity_id.strip():
            raise ValueError("entity_id cannot be empty")

        entity_type = entity_type.strip().lower()
        if entity_type in {"room", "device", "preset", "sensor"}:
            updated = self._upsert_home_state_entity(entity_type, entity_id, data, scope)
            self._write_json(self.home_state_path, updated)
        elif entity_type == "alias":
            updated = self._upsert_alias(entity_id, data)
            self._write_json(self.aliases_path, updated)
        elif entity_type == "rule":
            updated = self._upsert_rule(entity_id, data)
            self._write_json(self.rules_path, updated)
        else:
            raise ValueError(
                "entity_type must be one of: room, device, preset, sensor, alias, rule"
            )

        return {
            "status": "updated",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "scope": scope,
        }

    def _upsert_home_state_entity(
        self,
        entity_type: str,
        entity_id: str,
        data: Dict[str, Any],
        scope: Optional[str],
    ) -> Dict[str, Any]:
        home_state = self._read_json(self.home_state_path)
        home_state.setdefault("rooms", {})
        home_state.setdefault("presets", {"lighting": {}, "global": {}})
        home_state.setdefault("sensor_types", {})

        if entity_type == "room":
            room_entry = home_state["rooms"].setdefault(entity_id, {})
            room_entry.update(data)
            return home_state

        if entity_type == "device":
            room_name = scope or data.get("room")
            if not room_name:
                raise ValueError("device upsert requires scope=<room> or data.room")
            room_entry = home_state["rooms"].setdefault(room_name, {})
            room_entry.setdefault("device_catalog", {})
            payload = dict(data)
            payload.pop("room", None)
            room_entry["device_catalog"][entity_id] = payload
            return home_state

        if entity_type == "preset":
            preset_scope = (scope or data.get("scope") or "global").lower()
            if preset_scope not in {"lighting", "global"}:
                raise ValueError("preset scope must be lighting or global")
            payload = dict(data)
            payload.pop("scope", None)
            home_state["presets"].setdefault(preset_scope, {})
            home_state["presets"][preset_scope][entity_id] = payload
            return home_state

        if entity_type == "sensor":
            sensor_scope = scope or data.get("room")
            payload = dict(data)
            payload.pop("room", None)
            if sensor_scope:
                room_entry = home_state["rooms"].setdefault(sensor_scope, {})
                room_entry.setdefault("sensor_catalog", {})
                room_entry["sensor_catalog"][entity_id] = payload
            else:
                home_state["sensor_types"][entity_id] = payload
            return home_state

        return home_state

    def _upsert_alias(self, alias_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        aliases = self._read_json(self.aliases_path)
        aliases.setdefault("entries", {})
        aliases["entries"][alias_key] = data
        return aliases

    def _upsert_rule(self, rule_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        rules = self._read_json(self.rules_path)
        rules.setdefault("rules", {})
        rules["rules"][rule_id] = data
        return rules

