"""One polling cycle for all stations: fetch, archive, merge, store.

Planned stops are cached in memory per (station, hour) for a sliding window around now.
Every changes poll merges the cached plan with the full change feed and upserts the result,
so a stop's row always holds its latest known state. A failing station never stops the others.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from tracker.collector.client import TimetablesClient
from tracker.collector.parser import BERLIN


@dataclass(frozen=True)
class CycleResult:
    eva: str
    stops_saved: int = 0
    error: str | None = None  # set when this station failed in this cycle


class Poller:
    def __init__(
        self,
        client: TimetablesClient,
        session_factory: sessionmaker[Session],
        *,
        stations: Mapping[str, str],  # eva -> name
        archive_dir: Path | None = None,  # None: do not archive
        hours_back: int = 2,
        hours_ahead: int = 2,
        clock: Callable[[], datetime] = lambda: datetime.now(BERLIN),
        sleep: Callable[[float], None] = time.sleep,  # passed to call_with_retries
    ):
        raise NotImplementedError  # week 2, task A

    def refresh_plans(self) -> list[CycleResult]:
        """Fetch planned hours in [now - hours_back, now + hours_ahead] not cached yet.

        Drops cached hours that left the window. One result per station.
        """
        raise NotImplementedError

    def poll_changes(self) -> list[CycleResult]:
        """Fetch ``fchg`` per station, merge with cached plans, upsert stops in the window.

        Commits per station. One result per station, with ``stops_saved`` or ``error``.
        """
        raise NotImplementedError
