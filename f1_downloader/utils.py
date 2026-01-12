"""Utility functions for F1 Track Downloader."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from f1_downloader.config import Config


def setup_logging(config: Config) -> logging.Logger:
    """Setup logging to console and file."""

    config.log_dir.mkdir(exist_ok=True)

    log_file = config.log_dir / f"download_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger("f1downloader")
    logger.setLevel(logging.INFO)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logger.addHandler(file_handler)

    return logger


def atomic_write(data: dict[str, Any], path: Path, logger: logging.Logger) -> bool:
    """
    Atomically write JSON to file.

    Uses temp file + rename to prevent corruption on interruption.
    """
    path.parent.mkdir(exist_ok=True)
    tmp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".geojson",
            dir=path.parent,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)

        tmp_path.rename(path)

        return True

    except Exception as e:
        logger.error(f"    Write error: {e}")

        if tmp_path and tmp_path.exists():
            tmp_path.unlink()

        return False


