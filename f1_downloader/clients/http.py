"""Base HTTP client with common functionality."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from f1_downloader.config import Config


class HttpClient:
    """Base HTTP client with configured headers and timeout."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._session.headers.update(config.headers)

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        """Make GET request."""

        return self._session.get(
            url,
            params=params,
            timeout=timeout or self.config.timeout,
        )

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        """Make POST request."""

        return self._session.post(
            url,
            data=data,
            timeout=timeout or self.config.timeout,
        )

    def head(self, url: str, timeout: int | None = None) -> requests.Response:
        """Make HEAD request."""

        return self._session.head(
            url,
            timeout=timeout or self.config.timeout,
        )

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any] | None:
        """Make GET request and return JSON or None on error."""
        try:
            resp = self.get(url, params=params, timeout=timeout)
            resp.raise_for_status()

            return resp.json()
        except (requests.RequestException, ValueError):
            return None
