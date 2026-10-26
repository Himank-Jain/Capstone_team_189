"""Canonical Phase 3 API package."""

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Read the repository-root .env so settings work without exporting them.

    Real environment variables always win (override=False). Tests set
    CAPSTONE_SKIP_DOTENV=1 so a developer's real credentials are never used.
    """
    if os.getenv("CAPSTONE_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is in requirements.txt; tolerate its absence
        return
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


_load_dotenv()
