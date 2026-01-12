"""OpenStreetMap API client for verification."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from f1_downloader.config import Config


class OsmClient:
    """Client for OpenStreetMap API (not Overpass)."""

    OSM_API_BASE = "https://www.openstreetmap.org/api/0.6"

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._session.headers.update(config.headers)

    def verify_exists(self, osm_id: int, osm_type: str = "relation") -> bool:
        """Check if OSM element exists."""

        try:
            resp = self._session.head(
                f"{self.OSM_API_BASE}/{osm_type}/{osm_id}",
                timeout=10,
            )

            return resp.status_code == 200
        except requests.RequestException:
            return True  # Assume exists on network error

    def get_version(self, osm_id: int, osm_type: str = "relation") -> int | None:
        """Get current OSM element version."""

        try:
            resp = self._session.get(
                f"{self.OSM_API_BASE}/{osm_type}/{osm_id}.json",
                timeout=10,
            )

            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                elements = data.get("elements", [])

                if elements:
                    return elements[0].get("version")
        except (requests.RequestException, KeyError, ValueError):
            pass

        return None
