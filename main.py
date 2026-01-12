"""
F1 Track Downloader v1.0.0

Downloads Formula 1 circuit geometries from OpenStreetMap via Wikidata.

Usage: uv run main.py [--check-update]
"""

from f1_downloader.cli import main

if __name__ == "__main__":
    main()
