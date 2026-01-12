"""Overpass API client with automatic failover."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from f1_downloader.config import Config


class OverpassClient:
    """Client for Overpass API with multiple server failover and caching."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._session.headers.update(config.headers)
        self._current_server: str | None = None
        self._last_request_time: float = 0
        # In-memory cache for geometry to avoid duplicate requests
        self._geometry_cache: dict[tuple[int, str], dict[str, Any]] = {}

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)
        self._last_request_time = time.time()

    def query(
        self,
        query: str,
        timeout: int | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Execute Overpass query with automatic failover.

        Returns (data, server_name) tuple. Both are None if all servers fail.

        Smart retry logic:
        - If ALL servers timeout → query is too heavy, skip retry
        - Retry only for rate limits (429) or mixed errors
        """
        self._rate_limit()

        timeout = timeout or self.config.timeout
        last_error: Exception | None = None
        total_servers = len(self.config.overpass_servers)

        for attempt in range(self.config.max_retries):
            if attempt > 0:
                self.logger.info(f"       Retry {attempt + 1}/{self.config.max_retries}...")

            # Track error types in this round
            timeouts = 0
            rate_limits = 0
            other_errors = 0

            for idx, (server_name, server_url) in enumerate(self.config.overpass_servers, 1):
                try:
                    resp = self._session.post(
                        server_url,
                        data={"data": query},
                        timeout=timeout,
                    )

                    if resp.status_code == 200:
                        if self._current_server is None:
                            self.logger.info(f"       Using Overpass server: {server_name}")
                        elif self._current_server != server_name:
                            self.logger.info(
                                f"       Server switched: {self._current_server} -> {server_name}"
                            )
                        self._current_server = server_name

                        return resp.json(), server_name

                    # Server returned error
                    if resp.status_code == 429:
                        rate_limits += 1
                        self.logger.info(
                            f"       [{idx}/{total_servers}] {server_name}: rate limited (429), trying next..."
                        )
                    elif resp.status_code == 504:
                        timeouts += 1  # Gateway timeout = server-side timeout
                        self.logger.info(
                            f"       [{idx}/{total_servers}] {server_name}: gateway timeout (504), trying next..."
                        )
                    else:
                        other_errors += 1
                        self.logger.info(
                            f"       [{idx}/{total_servers}] {server_name}: error {resp.status_code}, trying next..."
                        )
                    continue

                except requests.exceptions.Timeout:
                    timeouts += 1
                    self.logger.info(
                        f"       [{idx}/{total_servers}] {server_name}: timeout ({timeout}s), trying next..."
                    )
                    continue

                except requests.RequestException as e:
                    last_error = e
                    other_errors += 1
                    self.logger.info(
                        f"       [{idx}/{total_servers}] {server_name}: connection error, trying next..."
                    )
                    continue

            # All servers failed this round - decide whether to retry
            if rate_limits == 0:
                # No rate limits - all servers either timed out or had connection errors
                # Retry won't help, the query is too heavy or servers are down
                self.logger.warning(
                    f"       All {total_servers} servers failed ({timeouts} timeouts, {other_errors} errors) - skipping retry"
                )
                return None, None

            # Retry only if we got rate limited (waiting might help)
            if attempt < self.config.max_retries - 1:
                wait = self.config.retry_delay * (attempt + 2)  # Extra wait for rate limits
                self.logger.info(
                    f"       {rate_limits} server(s) rate limited, waiting {wait}s before retry..."
                )
                time.sleep(wait)

        # All retries exhausted
        self.logger.warning(
            f"       All servers failed after {self.config.max_retries} attempts"
        )
        if last_error:
            self.logger.debug(f"       Last error: {last_error}")

        return None, None

    def _circuit_score(self, element: dict[str, Any]) -> int:
        """
        Score element by likelihood of being an actual circuit.
        Higher score = more likely to be the circuit we want.
        """

        tags = element.get("tags", {})
        score = 0

        # Strong circuit indicators (high priority)
        if tags.get("type") == "circuit":
            score += 100
        if tags.get("highway") == "raceway":
            score += 50

        # Medium indicators
        if "motor" in tags.get("sport", ""):
            score += 10
        if tags.get("leisure") == "track":
            score += 10

        # Negative indicators (likely a complex, not the track)
        if tags.get("type") in ("multipolygon", "site"):
            score -= 30
        if tags.get("leisure") == "sports_centre":
            score -= 50
        if tags.get("highway") == "services":
            score -= 60  # Service station, definitely not a circuit
        if "landuse" in tags or "amenity" in tags:
            score -= 20

        # Prefer relations over ways (small bonus)
        if element.get("type") == "relation":
            score += 5

        return score

    def _find_circuit_in_complex(
        self,
        parent_id: int,
        parent_type: str,
    ) -> tuple[int | None, str | None, str | None]:
        """
        Recursively search inside a sports complex for the actual circuit.
        Uses >> operator for recursive descent.
        """

        query = f"""[out:json][timeout:60];
{parent_type}({parent_id});
>>;
(
  nwr._["type"="circuit"];
  nwr._["highway"="raceway"];
);
out body;"""

        data, server = self.query(query, timeout=90)

        if data and data.get("elements"):
            # Use same scoring logic
            scored = [(self._circuit_score(el), el) for el in data["elements"]]
            scored.sort(key=lambda x: x[0], reverse=True)

            if scored and scored[0][0] > 0:  # Only return if positive score
                best = scored[0][1]
                return best["id"], best["type"], server

        return None, None, None

    def find_by_wikidata_tag(
        self,
        qid: str,
    ) -> tuple[int | None, str | None, str | None]:
        """
        Find OSM element by wikidata tag, preferring actual circuits.

        Returns (osm_id, osm_type, server_name).
        """

        query = f'[out:json][timeout:25];(relation["wikidata"="{qid}"];way["wikidata"="{qid}"];);out body;'
        data, server = self.query(query)

        if data:
            elements = data.get("elements", [])
            if not elements:
                return None, None, None

            # Score all elements and pick the best one
            scored = [(self._circuit_score(el), el) for el in elements]
            scored.sort(key=lambda x: x[0], reverse=True)

            best_score, best = scored[0]
            best_tags = best.get("tags", {})

            # Warn if multiple high-scoring candidates (ambiguous result)
            high_score_count = sum(1 for s, _ in scored if s > 50)
            if high_score_count > 1:
                self.logger.warning(
                    f"       Multiple high-scoring elements found ({high_score_count}), using first"
                )

            # Check if best is still a complex (needs recursive descent)
            is_complex = (
                best_score <= 0
                or best_tags.get("type") in ("site", "multipolygon")
                or best_tags.get("leisure") == "sports_centre"
            )

            if is_complex:
                self.logger.info("       -> found complex, searching inside...")
                inner_id, inner_type, srv = self._find_circuit_in_complex(
                    best["id"], best["type"]
                )
                if inner_id:
                    return inner_id, inner_type, srv or server

            return best["id"], best["type"], server

        return None, None, None

    def find_by_name(
        self,
        search_name: str,
    ) -> tuple[int | None, str | None, str | None]:
        """
        Search OSM by circuit name, preferring actual circuits.

        Returns (osm_id, osm_type, server_name).
        """

        query = f"""[out:json][timeout:30];
(
  relation["leisure"="track"]["name"~"{search_name}",i];
  relation["sport"~"motor"]["name"~"{search_name}",i];
  relation["highway"="raceway"]["name"~"{search_name}",i];
  relation["type"="circuit"]["name"~"{search_name}",i];
  way["leisure"="track"]["name"~"{search_name}",i];
  way["sport"~"motor"]["name"~"{search_name}",i];
  way["highway"="raceway"]["name"~"{search_name}",i];
);
out body;"""

        data, server = self.query(query)

        if data and data.get("elements"):
            elements = data["elements"]

            # Score all elements and pick the best one
            scored = [(self._circuit_score(el), el) for el in elements]
            scored.sort(key=lambda x: x[0], reverse=True)

            best_score, best = scored[0]
            best_tags = best.get("tags", {})

            # Warn if multiple high-scoring candidates
            high_score_count = sum(1 for s, _ in scored if s > 50)
            if high_score_count > 1:
                self.logger.warning(
                    f"       Multiple high-scoring elements found ({high_score_count}), using first"
                )

            # Check if best is still a complex (needs recursive descent)
            is_complex = (
                best_score <= 0
                or best_tags.get("type") in ("site", "multipolygon")
                or best_tags.get("leisure") == "sports_centre"
            )

            if is_complex:
                self.logger.info("       -> found complex, searching inside...")
                inner_id, inner_type, srv = self._find_circuit_in_complex(
                    best["id"], best["type"]
                )
                if inner_id:
                    return inner_id, inner_type, srv or server

            return best["id"], best["type"], server

        return None, None, None

    def get_geometry(
        self,
        osm_id: int,
        osm_type: str = "relation",
        use_cache: bool = True,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Get geometry for OSM element.

        Returns (element_data, server_name).
        Uses in-memory cache to avoid duplicate requests.
        """
        cache_key = (osm_id, osm_type)

        # Check cache first
        if use_cache and cache_key in self._geometry_cache:
            self.logger.debug(f"    Geometry cache hit: {osm_type} {osm_id}")
            return self._geometry_cache[cache_key], "cache"

        query = f"[out:json][timeout:60];{osm_type}({osm_id});out geom;"
        data, server = self.query(query, timeout=90)

        if data and data.get("elements"):
            element = data["elements"][0]
            # Store in cache
            self._geometry_cache[cache_key] = element
            return element, server

        return None, server

    def find_by_wikidata_tags_batch(
        self,
        qids: list[str],
    ) -> dict[str, tuple[int | None, str | None, int]]:
        """
        Find OSM elements for multiple Q-IDs in one query.

        Returns dict mapping Q-ID -> (osm_id, osm_type, score).
        Much more efficient than calling find_by_wikidata_tag() for each Q-ID.
        Score is computed from tags, no extra geometry request needed.
        """
        if not qids:
            return {}

        # Build query for all Q-IDs at once
        qid_filters = "".join(f'relation["wikidata"="{qid}"];way["wikidata"="{qid}"];' for qid in qids)
        query = f"[out:json][timeout:60];({qid_filters});out body;"

        data, _ = self.query(query, timeout=90)
        results: dict[str, tuple[int | None, str | None, int]] = {qid: (None, None, 0) for qid in qids}

        if not data:
            return results

        elements = data.get("elements", [])
        if not elements:
            return results

        # Group elements by their wikidata tag
        elements_by_qid: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qids}
        for el in elements:
            wikidata_tag = el.get("tags", {}).get("wikidata")
            if wikidata_tag and wikidata_tag in elements_by_qid:
                elements_by_qid[wikidata_tag].append(el)

        # For each Q-ID, pick the best element
        for qid, qid_elements in elements_by_qid.items():
            if not qid_elements:
                continue

            # Score and pick best
            scored = [(self._circuit_score(el), el) for el in qid_elements]
            scored.sort(key=lambda x: x[0], reverse=True)

            best_score, best = scored[0]
            best_tags = best.get("tags", {})

            # Check if it's a complex that needs recursive descent
            is_complex = (
                best_score <= 0
                or best_tags.get("type") in ("site", "multipolygon")
                or best_tags.get("leisure") == "sports_centre"
            )

            if is_complex:
                self.logger.info(f"       -> {qid}: found complex, searching inside...")
                inner_id, inner_type, _ = self._find_circuit_in_complex(
                    best["id"], best["type"]
                )
                if inner_id and inner_type:
                    # Get score for inner element (from cache if available)
                    inner_el, _ = self.get_geometry(inner_id, inner_type)
                    inner_score = self._circuit_score(inner_el) if inner_el else 0
                    self.logger.info(f"       -> {qid}: found {inner_type} {inner_id}")
                    results[qid] = (inner_id, inner_type, inner_score)
                    continue

            results[qid] = (best["id"], best["type"], best_score)

        return results

    def clear_cache(self) -> None:
        """Clear the in-memory geometry cache."""
        self._geometry_cache.clear()
