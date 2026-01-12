"""Circuit cache management."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from f1_downloader.models import CacheEntry


# Default cache structure with schema documentation
DEFAULT_CACHE: dict[str, Any] = {
    "_schema": {
        "version": 1,
        "description": "F1 Circuit ID mappings cache",
        "fields": {
            "osm_id": "OpenStreetMap element ID (number or null)",
            "osm_type": "Element type: relation or way",
            "wikidata_id": "Wikidata Q-ID (e.g. Q173099)",
            "search_method": "How found: manual/P402/wikidata_tag/osm_name",
            "search_name": "Which name variant matched",
            "verified_at": "Last verification timestamp",
            "manual": "true = won't be auto-updated",
            "comment": "Notes (auto-added for TODO items)",
            "osm_version": "OSM element version (for update checking)",
        },
    },
    "circuits": {},
}


class CircuitCache:
    """Manages circuit ID mappings cache."""

    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self.path = path
        self.logger = logger

        self._data: dict[str, Any] = DEFAULT_CACHE.copy()
        self._load()

    def _load(self) -> None:
        """Load cache from file."""

        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._data = {**DEFAULT_CACHE, **data}

                    if "circuits" not in self._data:
                        self._data["circuits"] = {}

            except (json.JSONDecodeError, OSError) as e:
                self.logger.warning(f"Failed to load cache: {e}")

                self._data = DEFAULT_CACHE.copy()
        else:
            self._data = DEFAULT_CACHE.copy()
            self.save()  # Create file with schema

    def save(self) -> None:
        """Save cache to file."""

        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

        except OSError as e:
            self.logger.warning(f"Failed to save cache: {e}")

    def get(self, name: str) -> CacheEntry | None:
        """Get cached entry for circuit name."""

        circuits = self._data.get("circuits", {})

        if name in circuits:
            return CacheEntry.from_dict(circuits[name])

        return None

    def set(
        self,
        name: str,
        osm_id: int | None,
        osm_type: str | None = None,
        wikidata_id: str | None = None,
        method: str | None = None,
        search_name: str | None = None,
        comment: str | None = None,
    ) -> None:
        """
        Save circuit to cache.

        Won't overwrite entries marked as manual.
        """

        if "circuits" not in self._data:
            self._data["circuits"] = {}

        existing = self._data["circuits"].get(name, {})

        if existing.get("manual"):
            return

        # Circuits without OSM ID need manual verification
        needs_manual = osm_id is None

        entry = CacheEntry(
            osm_id=osm_id,
            osm_type=osm_type,  # type: ignore
            wikidata_id=wikidata_id,
            search_method=method,
            search_name=search_name,
            verified_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            manual=needs_manual,
            comment=comment,
        )

        if needs_manual and not comment:
            entry.comment = "TODO: verify OSM ID manually"

            if wikidata_id:
                entry.comment += f" (check https://www.wikidata.org/wiki/{wikidata_id})"

        self._data["circuits"][name] = entry.to_dict()
        self.save()

    def update_version(self, name: str, version: int) -> None:
        """Update OSM version for a circuit."""

        if "circuits" not in self._data:
            return

        if name in self._data["circuits"]:
            self._data["circuits"][name]["osm_version"] = version
            self.save()

    @property
    def stats(self) -> tuple[int, int]:
        """Return (manual_count, auto_count) statistics."""

        circuits = self._data.get("circuits", {})
        manual = sum(1 for c in circuits.values() if c.get("manual"))
        auto = len(circuits) - manual

        return manual, auto
