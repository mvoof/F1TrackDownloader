"""Business logic for circuit search and processing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1_downloader.cache import CircuitCache
from f1_downloader.clients.osm import OsmClient
from f1_downloader.clients.overpass import OverpassClient
from f1_downloader.clients.wikidata import WikidataClient
from f1_downloader.models import Circuit, ProcessResult, SearchResult
from f1_downloader.utils import atomic_write


@dataclass
class _Candidate:
    """Internal candidate for OSM search results."""

    osm_id: int
    osm_type: str
    qid: str
    method: str
    search_name: str
    score: int
    from_circuit_name: bool = False  # True if Q-ID found via circuit name (not Grand Prix)


def search_osm_id(
    circuit: Circuit,
    cache: CircuitCache,
    wikidata: WikidataClient,
    overpass: OverpassClient,
    osm: OsmClient,
    logger: logging.Logger,
) -> SearchResult | None:
    """
    Find OSM element ID using cache and Wikidata.

    Search order:
    1. Check cache
    2. Collect all Q-IDs from all name variants
    3. For each unique Q-ID:
       a. Check Wikidata P402 property (direct OSM link)
       b. Search OSM for wikidata tag
       c. Collect all found candidates with scores
    4. If multiple candidates found -> pick best, add comment about others
    5. If no candidates from Wikidata -> try direct OSM name search
    6. Cache result
    """

    # Check cache first
    cached = cache.get(circuit.name)

    if cached:
        osm_id = cached.osm_id
        osm_type = cached.osm_type or "relation"

        # Manual entry with no OSM
        if osm_id is None and cached.manual:
            return None

        # Verify cached ID still exists
        if osm_id:
            if osm.verify_exists(osm_id, osm_type):
                method = cached.search_method or "cached"

                logger.info(f"    Cache hit: OSM {osm_type} {osm_id} (via {method})")

                return SearchResult(
                    osm_id=osm_id,
                    osm_type=osm_type,  # type: ignore
                    method=f"cache ({method})",
                    wikidata_id=cached.wikidata_id,
                )
            else:
                logger.warning(f"    Cached OSM ID {osm_id} no longer exists!")

    # Step 1: Collect all Q-IDs from all search names
    logger.info("    Step 1: Collecting Q-IDs from Wikidata...")

    all_qids: dict[str, str] = {}  # qid -> search_name that found it
    circuit_name_qids: set[str] = set()  # Q-IDs found via circuit name (first search_name)

    for i, search_name in enumerate(circuit.search_names):
        logger.info(f'       Searching for "{search_name}"...')
        qids = wikidata.find_ids(search_name)

        for qid in qids:
            if qid not in all_qids:
                all_qids[qid] = search_name
                logger.info(f"          -> {qid}")

                # Track Q-IDs found via circuit name (not Grand Prix)
                if i == 0:
                    circuit_name_qids.add(qid)

    if not all_qids:
        logger.info("       -> no Q-IDs found")

    # Step 2: Batch query for P402 properties (one SPARQL request instead of N)
    candidates: list[_Candidate] = []
    checked_osm_ids: set[int] = set()  # Avoid duplicates

    if all_qids:
        qid_list = list(all_qids.keys())
        logger.info(f"    Step 2: Batch checking P402 for {len(qid_list)} Q-IDs...")
        p402_results = wikidata.get_p402_batch(qid_list)

        for qid, p402_id in p402_results.items():
            if p402_id and p402_id not in checked_osm_ids:
                checked_osm_ids.add(p402_id)
                search_name = all_qids[qid]
                logger.info(f"       -> {qid}: P402 found: relation {p402_id}")

                # P402 is always a relation, get its score (will be cached)
                element_data, _ = overpass.get_geometry(p402_id, "relation")
                score = overpass._circuit_score(element_data) if element_data else 0

                candidates.append(
                    _Candidate(
                        osm_id=p402_id,
                        osm_type="relation",
                        qid=qid,
                        method="P402",
                        search_name=search_name,
                        score=score + 20,  # Bonus for P402 (authoritative source)
                        from_circuit_name=(qid in circuit_name_qids),
                    )
                )

        # Step 3: Batch search OSM for wikidata tags (one Overpass request)
        logger.info(f"    Step 3: Batch searching OSM for {len(qid_list)} wikidata tags...")
        osm_results = overpass.find_by_wikidata_tags_batch(qid_list)

        for qid, (osm_id, osm_type, score) in osm_results.items():
            if osm_id and osm_type and osm_id not in checked_osm_ids:
                checked_osm_ids.add(osm_id)
                search_name = all_qids[qid]
                logger.info(f"       -> {qid}: found {osm_type} {osm_id} (score={score})")

                candidates.append(
                    _Candidate(
                        osm_id=osm_id,
                        osm_type=osm_type,
                        qid=qid,
                        method="wikidata_tag",
                        search_name=search_name,
                        score=score,
                        from_circuit_name=(qid in circuit_name_qids),
                    )
                )

    # Step 4: Try name search only if:
    # - No candidates at all, OR
    # - No candidate from circuit name Q-ID AND best score is low
    has_circuit_name_candidate = any(c.from_circuit_name for c in candidates)
    best_wikidata_score = max((c.score for c in candidates), default=-999)
    should_try_name_search = not candidates or (not has_circuit_name_candidate and best_wikidata_score < 50)

    if should_try_name_search:
        # Only search by circuit name (first search_name), not Grand Prix names
        # This reduces API load significantly
        search_name = circuit.search_names[0] if circuit.search_names else circuit.name
        logger.info(f'    Step 4: Trying OSM name search for "{search_name}"...')
        osm_id, osm_type, server = overpass.find_by_name(search_name)

        if osm_id and osm_type and osm_id not in checked_osm_ids:
            checked_osm_ids.add(osm_id)
            logger.info(f"       -> found {osm_type} {osm_id} (via {server})")

            # Get score for this element
            element_data, _ = overpass.get_geometry(osm_id, osm_type)
            score = overpass._circuit_score(element_data) if element_data else 0

            candidates.append(
                _Candidate(
                    osm_id=osm_id,
                    osm_type=osm_type,
                    qid="",  # No Wikidata Q-ID for name search
                    method="osm_name",
                    search_name=search_name,
                    score=score,
                    from_circuit_name=True,  # Circuit name search
                )
            )
        elif osm_id and osm_id in checked_osm_ids:
            logger.info(f"       -> {osm_type} {osm_id} already in candidates")
        else:
            logger.info("       -> not found")

    # Step 4: Pick best candidate
    if candidates:
        # Sort: prefer circuit name matches, then by score (descending)
        candidates.sort(key=lambda c: (c.from_circuit_name, c.score), reverse=True)
        best = candidates[0]

        logger.info(
            f"    Found {len(candidates)} candidate(s), "
            f"best: {best.osm_type} {best.osm_id} (score={best.score}, "
            f"from_circuit_name={best.from_circuit_name}, method={best.method})"
        )

        # Build comment if multiple candidates
        comment: str | None = None

        if len(candidates) > 1:
            others = [
                f"{c.osm_type}/{c.osm_id} (via '{c.search_name}', {c.qid or 'name'}, score={c.score})"
                for c in candidates[1:]
            ]
            comment = f"Also found: {', '.join(others)}. Please verify manually."
            logger.warning(f"    Multiple candidates found: {comment}")

        cache.set(
            circuit.name,
            best.osm_id,
            best.osm_type,
            best.qid or None,  # Don't store empty string
            best.method,
            best.search_name,
            comment,
        )

        method_str = f"Wikidata {best.method}" if best.qid else "Overpass name search"

        return SearchResult(
            osm_id=best.osm_id,
            osm_type=best.osm_type,  # type: ignore
            method=method_str,
            wikidata_id=best.qid or None,
        )

    # No candidates found anywhere
    if all_qids:
        # Wikidata knows about this circuit but it's not in OSM
        first_qid = next(iter(all_qids))
        logger.info("    Wikidata knows this circuit, but it's not in OSM")
        cache.set(circuit.name, None, None, first_qid, None, None)

        return None

    # Not found anywhere
    cache.set(circuit.name, None, None, None, None, None)

    return None


def element_to_geojson(element: dict[str, Any]) -> dict[str, Any]:
    """Convert Overpass element (relation or way) to GeoJSON."""

    features: list[dict[str, Any]] = []
    osm_type = element.get("type", "relation")

    if osm_type == "relation":
        # Relation: geometry is in members
        for member in element.get("members", []):
            if member["type"] == "way" and "geometry" in member:
                coords = [[p["lon"], p["lat"]] for p in member["geometry"]]
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "role": member.get("role", ""),
                            "ref": member.get("ref"),
                        },
                        "geometry": {"type": "LineString", "coordinates": coords},
                    }
                )
    elif osm_type == "way":
        # Way: geometry is directly in element
        if "geometry" in element:
            coords = [[p["lon"], p["lat"]] for p in element["geometry"]]
            features.append(
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def process_circuit(
    circuit: Circuit,
    output_dir: Path,
    cache: CircuitCache,
    wikidata: WikidataClient,
    overpass: OverpassClient,
    osm: OsmClient,
    logger: logging.Logger,
    check_update: bool = False,
) -> ProcessResult:
    """Process a single circuit and save its geometry."""

    out_path = output_dir / f"{circuit.safe_filename}.geojson"

    # Skip if file already exists (no API calls needed)
    if out_path.exists() and not check_update:
        return ProcessResult(
            success=True,
            message="Already exists",
            is_skipped=True,
        )

    # Find OSM ID
    result = search_osm_id(circuit, cache, wikidata, overpass, osm, logger)

    if not result:
        # Check if it was a manual skip
        cached = cache.get(circuit.name)

        if cached and cached.manual and cached.osm_id is None:
            return ProcessResult(
                success=False,
                message="The race track may no longer exist.\n Skipped (manual=true and osm_id=null in circuit_mappings.json)",
            )

        wikidata_id = cached.wikidata_id if cached else None

        if wikidata_id:
            return ProcessResult(
                success=False,
                message=(
                    f"Not found in OpenStreetMap\n"
                    f"       Wikidata: {wikidata_id}\n"
                    f"       Actions:\n"
                    f"          1. Check https://www.wikidata.org/wiki/{wikidata_id}\n"
                    f"          2. Find circuit at https://www.openstreetmap.org\n"
                    f"          3. Add OSM ID to circuit_mappings.json"
                ),
            )

        return ProcessResult(
            success=False,
            message=(
                "Not found in Wikidata or OSM\n"
                "       Actions:\n"
                "          1. Find circuit at https://www.openstreetmap.org\n"
                "          2. Add OSM ID to circuit_mappings.json:\n"
                f'             "{circuit.name}": {{"osm_id": 12345, "osm_type": "way", "manual": true}}'
            ),
        )

    # Check for updates using version from cache
    remote_ver = None

    if out_path.exists() and check_update:
        cached = cache.get(circuit.name)
        local_ver = cached.osm_version if cached else None
        remote_ver = osm.get_version(result.osm_id, result.osm_type)

        if local_ver and remote_ver and local_ver >= remote_ver:
            return ProcessResult(
                success=True,
                message=f"Up to date (v{local_ver})",
                is_skipped=True,
            )

        logger.info(f"    Updating: v{local_ver} -> v{remote_ver}")

    # Get geometry
    element, server = overpass.get_geometry(result.osm_id, result.osm_type)

    if not element:
        return ProcessResult(
            success=False,
            message=(
                f"Failed to get geometry from Overpass API\n"
                f"       OSM {result.osm_type}: {result.osm_id}\n"
                f"       Possible causes:\n"
                f"          - All Overpass servers are overloaded or unavailable\n"
                f"          - Try running the script later\n"
                f"          - Check: https://www.openstreetmap.org/{result.osm_type}/{result.osm_id}"
            ),
        )

    # Convert and save
    geojson = element_to_geojson(element)

    if not geojson["features"]:
        return ProcessResult(
            success=False,
            message=(
                f"OSM {result.osm_type} has no geometry\n"
                f"       OSM {result.osm_type}: {result.osm_id}\n"
                f"       Possible causes:\n"
                f"          - Element exists but has no geometry data\n"
                f"          - Check: https://www.openstreetmap.org/{result.osm_type}/{result.osm_id}\n"
                f"          - May need to find a different OSM ID for this circuit"
            ),
        )

    if atomic_write(geojson, out_path, logger):
        # Update version in cache
        if remote_ver is None:
            remote_ver = osm.get_version(result.osm_id, result.osm_type)

        if remote_ver:
            cache.update_version(circuit.name, remote_ver)

        return ProcessResult(
            success=True,
            message=f"Saved via {result.method} (OSM {result.osm_type}: {result.osm_id}, server: {server})",
        )

    return ProcessResult(
        success=False,
        message=(
            f"Failed to save file {out_path}\n"
            "       Check write permissions for tracks_geojson/"
        ),
    )
