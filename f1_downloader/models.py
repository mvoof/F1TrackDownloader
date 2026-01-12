"""Data models for F1 Track Downloader."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Circuit:
    """F1 racing circuit from Wikipedia."""

    name: str
    location: str
    country: str
    grands_prix: str = ""

    @property
    def safe_filename(self) -> str:
        """Convert name to filesystem-safe filename."""

        normalized = unicodedata.normalize("NFKD", self.name)
        ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
        no_special = re.sub(r"[^\w\s-]", "", ascii_only)

        return re.sub(r"[\s-]+", "_", no_special).strip("_")

    @property
    def search_names(self) -> list[str]:
        """
        Generate alternative names for searching.
        """

        names = [self.name]

        # Add Grand Prix names from Wikipedia (e.g., "Australian Grand Prix")
        # May contain multiple names separated by comma
        if self.grands_prix:
            for gp_name in self.grands_prix.split(","):
                gp_name = gp_name.strip()

                if gp_name:
                    names.append(gp_name)

        return names


OsmType = Literal["relation", "way"]


@dataclass
class SearchResult:
    """Result of OSM ID search."""

    osm_id: int
    osm_type: OsmType
    method: str
    wikidata_id: str | None = None


@dataclass
class CacheEntry:
    """Single circuit entry in the cache."""

    osm_id: int | None
    osm_type: OsmType | None = None
    wikidata_id: str | None = None
    search_method: str | None = None
    search_name: str | None = None
    verified_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    manual: bool = False
    comment: str | None = None
    osm_version: int | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""

        result: dict = {
            "osm_id": self.osm_id,
            "osm_type": self.osm_type,
            "wikidata_id": self.wikidata_id,
            "search_method": self.search_method,
            "search_name": self.search_name,
            "verified_at": self.verified_at,
            "manual": self.manual,
        }

        if self.comment:
            result["comment"] = self.comment

        if self.osm_version is not None:
            result["osm_version"] = self.osm_version

        return result

    @classmethod
    def from_dict(cls, data: dict) -> CacheEntry:
        """Create from dictionary (JSON deserialization)."""

        return cls(
            osm_id=data.get("osm_id"),
            osm_type=data.get("osm_type"),
            wikidata_id=data.get("wikidata_id"),
            search_method=data.get("search_method"),
            search_name=data.get("search_name"),
            verified_at=data.get("verified_at", ""),
            manual=data.get("manual", False),
            comment=data.get("comment"),
            osm_version=data.get("osm_version"),
        )


@dataclass
class ProcessResult:
    """Result of processing a single circuit."""

    success: bool
    message: str
    is_skipped: bool = False
