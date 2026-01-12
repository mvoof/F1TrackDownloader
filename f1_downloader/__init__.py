"""
F1 Track Downloader v1.0.0

Downloads Formula 1 circuit geometries from OpenStreetMap via Wikidata.
"""

__version__ = "1.0.0"

from f1_downloader.models import Circuit, SearchResult
from f1_downloader.config import Config

__all__ = ["Circuit", "SearchResult", "Config", "__version__"]
