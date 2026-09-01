"""Canonical filesystem locations for the project.

Everything is anchored to the repo root so the package works the same whether it is
invoked from the CLI, a notebook, the API, or a container. Override the data / reports
roots with the ``NA_DATA_DIR`` / ``NA_REPORTS_DIR`` environment variables (used by Docker).
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return start.resolve()


REPO_ROOT: Path = _find_repo_root(Path(__file__).parent)

CONFIG_DIR: Path = REPO_ROOT / "config"
PRESETS_DIR: Path = CONFIG_DIR / "presets"

DATA_DIR: Path = Path(os.environ.get("NA_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR: Path = DATA_DIR / "raw"
WAREHOUSE_DB: Path = Path(os.environ.get("NA_WAREHOUSE_DB", DATA_DIR / "warehouse.db"))

REPORTS_DIR: Path = Path(os.environ.get("NA_REPORTS_DIR", REPO_ROOT / "reports"))

NOTEBOOKS_DIR: Path = REPO_ROOT / "notebooks"


def ensure_dirs() -> None:
    """Create the writable directories if they do not exist yet."""
    for d in (DATA_DIR, RAW_DIR, REPORTS_DIR, PRESETS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def raw_feed_dir(feed: str, day: str | None = None) -> Path:
    """``data/raw/<feed>/dt=YYYY-MM-DD`` (day optional)."""
    p = RAW_DIR / feed
    if day:
        p = p / f"dt={day}"
    return p
