"""Configuration for F1 Track Downloader."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    # Directories
    output_dir: Path = field(default_factory=lambda: Path("tracks_geojson"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    mappings_file: Path = field(default_factory=lambda: Path("circuit_mappings.json"))

    # HTTP settings
    user_agent: str = "F1TrackDownloader/1.0"
    request_delay: float = 1.0
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5

    # API endpoints
    wikipedia_url: str = "https://en.wikipedia.org/wiki/List_of_Formula_One_circuits"
    wikidata_api: str = "https://www.wikidata.org/w/api.php"
    wikidata_entity: str = "https://www.wikidata.org/wiki/Special:EntityData"

    # Overpass API servers (with failover)
    overpass_servers: ClassVar[list[tuple[str, str]]] = [
        ("overpass-api.de", "https://overpass-api.de/api/interpreter"),
        ("kumi.systems", "https://overpass.kumi.systems/api/interpreter"),
        ("mail.ru", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
        ("private.coffee", "https://overpass.private.coffee/api/interpreter"),
        ("osm.jp", "https://overpass.osm.jp/api/interpreter"),
    ]

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers for requests."""
        return {"User-Agent": self.user_agent}

    def ensure_dirs(self) -> None:
        """Create output and log directories if they don't exist."""
        self.output_dir.mkdir(exist_ok=True)
        self.log_dir.mkdir(exist_ok=True)
