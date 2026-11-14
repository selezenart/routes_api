"""Keep every raw API response on disk, so data can be re-parsed later."""

from __future__ import annotations

import gzip
from datetime import datetime
from pathlib import Path

from tracker.collector.parser import BERLIN


def archive_response(root: Path, eva: str, kind: str, fetched_at: datetime, xml: str) -> Path:
    """Write ``xml`` gzip-compressed and return the file path.

    Layout: ``<root>/<YYYY-MM-DD>/<eva>/<kind>_<HHMMSS>.xml.gz``, with date and time taken
    from ``fetched_at`` in Europe/Berlin. ``kind`` is e.g. ``"fchg"`` or ``"plan_26111312"``.
    Creates folders as needed. Never overwrites: if the name exists, add ``_1``, ``_2``, ...
    """
    local = fetched_at.astimezone(BERLIN)
    folder = Path(root) / f"{local:%Y-%m-%d}" / eva
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}_{local:%H%M%S}"
    data = gzip.compress(xml.encode("utf-8"))
    suffix = 0
    while True:
        path = folder / f"{stem}{f'_{suffix}' if suffix else ''}.xml.gz"
        try:
            with path.open("xb") as handle:  # "x": fail instead of overwrite
                handle.write(data)
            return path
        except FileExistsError:
            suffix += 1
