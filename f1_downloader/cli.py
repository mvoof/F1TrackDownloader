"""Command-line interface for F1 Track Downloader."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from f1_downloader.cache import CircuitCache
from f1_downloader.clients.osm import OsmClient
from f1_downloader.clients.overpass import OverpassClient
from f1_downloader.clients.wikidata import WikidataClient
from f1_downloader.clients.wikipedia import WikipediaClient
from f1_downloader.config import Config
from f1_downloader.services import process_circuit
from f1_downloader.utils import setup_logging


def _handle_interrupt(_sig: int, _frame: object) -> None:
    """Handle Ctrl+C - exit immediately."""

    print("\n\nInterrupted by user. Exiting...")
    sys.exit(130)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Download F1 track geometries from OpenStreetMap"
    )

    parser.add_argument(
        "--check-update",
        action="store_true",
        help="Check for updates only",
    )

    return parser.parse_args()


def run(check_update: bool = False) -> None:
    """Main application logic."""

    # Setup
    config = Config()
    logger = setup_logging(config)
    config.ensure_dirs()

    # Initialize clients
    cache = CircuitCache(config.mappings_file, logger)
    overpass = OverpassClient(config, logger)
    wikidata = WikidataClient(config, logger)
    osm = OsmClient(config, logger)
    wikipedia = WikipediaClient(config, logger)

    # Show cache stats
    manual, auto = cache.stats

    logger.info(f"Cache: {manual} manual + {auto} auto-discovered mappings")

    # Fetch circuits from Wikipedia
    try:
        circuits = wikipedia.fetch_circuits()
    except Exception as e:
        logger.error(f"Failed to fetch circuits: {e}")
        sys.exit(1)

    if not circuits:
        logger.error("No circuits found")
        sys.exit(1)

    # Process circuits
    total = len(circuits)
    success = 0
    failed = 0
    skipped = 0
    failed_list: list[tuple[str, str]] = []

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Processing {total} circuits...")

    if check_update:
        logger.info("   (update check mode)")

    logger.info(f"{'=' * 60}\n")

    for idx, circuit in enumerate(circuits, 1):
        logger.info(f"[{idx}/{total}] {circuit.name}")

        result = process_circuit(
            circuit=circuit,
            output_dir=config.output_dir,
            cache=cache,
            wikidata=wikidata,
            overpass=overpass,
            osm=osm,
            logger=logger,
            check_update=check_update,
        )

        if result.success:
            if result.is_skipped:
                skipped += 1
            else:
                success += 1
            logger.info(f"    {result.message}")
        else:
            failed += 1
            failed_list.append((circuit.name, result.message))
            logger.warning(f"    {result.message}")

        time.sleep(config.request_delay)

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Results: {success} saved | {skipped} skipped | {failed} failed")
    logger.info(f"{'=' * 60}")

    if failed_list:
        logger.info("\nFailed circuits:\n")

        for name, reason in failed_list:
            logger.info(f"   - {name}")

            for line in reason.split("\n"):
                logger.info(f"     {line}")

            logger.info("")

        logger.info("=" * 60)
        logger.info("How to add a circuit manually:")
        logger.info("=" * 60)
        logger.info("   1. Find the circuit at https://www.openstreetmap.org")
        logger.info("   2. Copy the relation ID (number from URL)")
        logger.info("   3. Add to circuit_mappings.json:")
        logger.info('      "Circuit Name": {')
        logger.info('        "osm_id": 12345678,')
        logger.info('        "wikidata_id": "Q123456",')
        logger.info('        "manual": true')
        logger.info("      }")
        logger.info("")


def main() -> None:
    """Entry point for CLI."""

    signal.signal(signal.SIGINT, _handle_interrupt)
    args = parse_args()

    run(check_update=args.check_update)


if __name__ == "__main__":
    main()
