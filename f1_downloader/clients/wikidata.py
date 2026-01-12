"""Wikidata API client."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from f1_downloader.config import Config


class WikidataClient:
    """Client for Wikidata API with rate limiting."""

    # Keywords that indicate a circuit in Wikidata descriptions
    CIRCUIT_KEYWORDS = ("circuit", "track", "raceway", "motorsport", "racing")

    # SPARQL endpoint for batch queries
    SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._session.headers.update(config.headers)
        self._last_request_time: float = 0

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)
        self._last_request_time = time.time()

    def find_ids(self, name: str, limit: int = 5) -> list[str]:
        """
        Find Wikidata Q-IDs for a circuit name.

        Returns list of Q-IDs sorted by relevance (circuit-related first).
        """
        self._rate_limit()
        try:
            resp = self._session.get(
                self.config.wikidata_api,
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "en",
                    "format": "json",
                    "limit": limit,
                },
                timeout=15,
            )

            data = resp.json()
            results = data.get("search", [])

            if not results:
                return []

            # Score results: circuit-related get priority
            scored: list[tuple[int, str]] = []

            for r in results:
                desc = r.get("description", "").lower()
                score = 0

                # Prioritize circuit-related results
                if any(kw in desc for kw in self.CIRCUIT_KEYWORDS):
                    score += 10

                # Bonus for F1-specific
                if "formula" in desc or "f1" in desc:
                    score += 5

                scored.append((score, r["id"]))

            # Sort by score (descending), return Q-IDs
            scored.sort(key=lambda x: x[0], reverse=True)

            return [qid for _, qid in scored]

        except (requests.RequestException, KeyError, ValueError):
            return []

    def find_id(self, name: str) -> str | None:
        """
        Find Wikidata Q-ID for a circuit name (convenience wrapper).

        Returns first Q-ID or None if not found.
        """
        qids = self.find_ids(name, limit=1)
        return qids[0] if qids else None

    def get_p402(self, qid: str) -> int | None:
        """
        Get OSM relation ID from Wikidata P402 property.

        P402 is the "OpenStreetMap relation ID" property in Wikidata.
        Returns OSM relation ID or None if not set.
        """
        self._rate_limit()
        try:
            resp = self._session.get(
                f"{self.config.wikidata_entity}/{qid}.json",
                timeout=15,
            )

            data = resp.json()
            claims = data["entities"][qid].get("claims", {})

            if "P402" in claims:
                return int(claims["P402"][0]["mainsnak"]["datavalue"]["value"])

        except (requests.RequestException, KeyError, ValueError):
            pass

        return None

    def get_p402_batch(self, qids: list[str]) -> dict[str, int | None]:
        """
        Get OSM relation IDs for multiple Q-IDs in one SPARQL query.

        Returns dict mapping Q-ID -> OSM relation ID (or None if not set).
        Much more efficient than calling get_p402() for each Q-ID.
        """
        if not qids:
            return {}

        self._rate_limit()

        # Build SPARQL query for all Q-IDs
        values = " ".join(f"wd:{qid}" for qid in qids)
        query = f"""
SELECT ?item ?osmRelation WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P402 ?osmRelation. }}
}}
"""

        try:
            resp = self._session.get(
                self.SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
                timeout=30,
            )

            data = resp.json()
            results: dict[str, int | None] = {qid: None for qid in qids}

            for binding in data.get("results", {}).get("bindings", []):
                item_uri = binding.get("item", {}).get("value", "")
                qid = item_uri.split("/")[-1]  # Extract Q-ID from URI

                if "osmRelation" in binding:
                    try:
                        results[qid] = int(binding["osmRelation"]["value"])
                    except (ValueError, KeyError):
                        pass

            return results

        except (requests.RequestException, KeyError, ValueError) as e:
            self.logger.debug(f"SPARQL batch query failed: {e}")
            return {qid: None for qid in qids}
