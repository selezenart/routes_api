"""Keep every raw API response on disk, so data can be re-parsed later."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def archive_response(root: Path, eva: str, kind: str, fetched_at: datetime, xml: str) -> Path:
    """Write ``xml`` gzip-compressed and return the file path.

    Layout: ``<root>/<YYYY-MM-DD>/<eva>/<kind>_<HHMMSS>.xml.gz``, with date and time taken
    from ``fetched_at`` in Europe/Berlin. ``kind`` is e.g. ``"fchg"`` or ``"plan_26111312"``.
    Creates folders as needed. Never overwrites: if the name exists, add ``_1``, ``_2``, ...
    """
    raise NotImplementedError  # week 2, task A
