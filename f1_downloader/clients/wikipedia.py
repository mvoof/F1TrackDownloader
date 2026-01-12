"""Wikipedia client for fetching circuit list."""

from __future__ import annotations

import logging
import re
from io import StringIO
from typing import TYPE_CHECKING

import pandas as pd
import requests

if TYPE_CHECKING:
    from f1_downloader.config import Config

from f1_downloader.models import Circuit


def _clean_wiki_text(text: object) -> str:
    """Remove Wikipedia annotations from text."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    text_str = str(text)
    text_str = re.sub(r"\[.*?\]", "", text_str)
    text_str = re.sub(r"[*\u2020\u2021\u00a7\u00b6]", "", text_str)
    return text_str.strip()


class WikipediaClient:
    """Client for fetching F1 circuit data from Wikipedia."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._session.headers.update(config.headers)

    def fetch_circuits(self) -> list[Circuit]:
        """Fetch list of F1 circuits from Wikipedia."""

        self.logger.info("Fetching circuit list from Wikipedia...")

        resp = self._session.get(
            self.config.wikipedia_url,
            timeout=self.config.timeout,
        )

        resp.raise_for_status()

        tables = pd.read_html(StringIO(resp.text))
        circuits: list[Circuit] = []

        for table in tables:
            cols = set(table.columns)

            if {"Circuit", "Location", "Country"} <= cols:
                for _, row in table.iterrows():
                    name = _clean_wiki_text(row["Circuit"])

                    if name:
                        # Extract "Grands Prix" column if available
                        grands_prix = ""

                        if "Grands Prix" in cols:
                            grands_prix = _clean_wiki_text(row["Grands Prix"])

                        circuits.append(
                            Circuit(
                                name=name,
                                location=_clean_wiki_text(row["Location"]),
                                country=_clean_wiki_text(row["Country"]),
                                grands_prix=grands_prix,
                            )
                        )
                break

        self.logger.info(f"   Found {len(circuits)} circuits")

        return circuits
