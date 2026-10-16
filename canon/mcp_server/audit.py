"""Append-only audit log: one JSON line per tool call (who asked what, what was returned)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


def _cited(obj) -> set[str]:
    """Every record_id a response cites, at any depth."""
    if isinstance(obj, dict):
        found = {obj["record_id"]} if isinstance(obj.get("record_id"), str) else set()
        for v in obj.values():
            found |= _cited(v)
        return found
    if isinstance(obj, list):
        return set().union(*(_cited(v) for v in obj)) if obj else set()
    return set()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        tool: str,
        caller_id: str,
        known_caller: bool,
        query: str,
        response: BaseModel,
        withheld: int = 0,
    ) -> dict:
        data = response.model_dump(mode="json")
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "caller": caller_id,
            "known_caller": known_caller,
            "query": query,
            "found": data.get("found"),
            "entity_id": (data.get("customer") or {}).get("entity_id"),
            "partial_view": data.get("partial_view"),
            "records_cited": sorted(_cited(data)),
            "withheld_injection": withheld,
        }
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
