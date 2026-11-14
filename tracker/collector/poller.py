"""One polling cycle for all stations: fetch, archive, merge, store.

Planned stops are cached in memory per (station, hour) for a sliding window around now.
Every changes poll merges the cached plan with the full change feed and upserts the result,
so a stop's row always holds its latest known state. A failing station never stops the others.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tracker.collector.client import TimetablesClient, TimetablesError
from tracker.collector.archive import archive_response
from tracker.collector.merge import merge
from tracker.collector.parser import BERLIN, Stop, parse_timetable
from tracker.collector.retry import call_with_retries
from tracker.db.store import upsert_stops

logger = logging.getLogger("tracker.collector")


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
        self._client = client
        self._session_factory = session_factory
        self._stations = dict(stations)
        self._archive_dir = archive_dir
        self._hours_back = hours_back
        self._hours_ahead = hours_ahead
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()  # the scheduler may run both jobs on different threads
        # eva -> {hour start (UTC, whole hours) -> planned stops of that Berlin hour}
        self._plans: dict[str, dict[datetime, list[Stop]]] = {eva: {} for eva in self._stations}

    def _window_hours(self, now: datetime) -> list[datetime]:
        """Start of every hour touched by [now - hours_back, now + hours_ahead]."""
        first = _hour_start(now - timedelta(hours=self._hours_back))
        last = _hour_start(now + timedelta(hours=self._hours_ahead))
        count = int((last - first) / timedelta(hours=1)) + 1
        return [first + timedelta(hours=i) for i in range(count)]

    def refresh_plans(self) -> list[CycleResult]:
        """Fetch planned hours in [now - hours_back, now + hours_ahead] not cached yet.

        Drops cached hours that left the window. One result per station.
        """
        with self._lock:
            return self._refresh_plans()

    def _refresh_plans(self) -> list[CycleResult]:
        now = self._clock()
        hours = self._window_hours(now)
        results = []
        for eva, name in self._stations.items():
            cache = self._plans.setdefault(eva, {})
            for hour in [h for h in cache if h not in hours]:
                del cache[hour]
            fetched = 0
            error = None
            try:
                for hour in hours:
                    if hour in cache:
                        continue
                    xml = call_with_retries(lambda: self._client.plan(eva, hour), sleep=self._sleep)
                    self._archive(eva, f"plan_{hour.astimezone(BERLIN):%y%m%d%H}", now, xml)
                    cache[hour] = parse_timetable(xml).stops
                    fetched += 1
            except Exception as exc:  # one broken station must not stop the others
                error = str(exc) or type(exc).__name__
                logger.warning("plan %s (%s) failed: %s", name, eva, error)
            if error is None:
                logger.info("plan %s (%s): %d new hours cached, %d in window", name, eva, fetched, len(cache))
            results.append(CycleResult(eva, stops_saved=0, error=error))
        return results

    def poll_changes(self) -> list[CycleResult]:
        """Fetch ``fchg`` per station, merge with cached plans, upsert stops in the window.

        Commits per station. One result per station, with ``stops_saved`` or ``error``.
        """
        with self._lock:
            return self._poll_changes()

    def _poll_changes(self) -> list[CycleResult]:
        now = self._clock()
        hours = self._window_hours(now)
        if any(hour not in cache for cache in self._plans.values() for hour in hours):
            self._refresh_plans()  # e.g. a new hour began since the last refresh
        start, end = hours[0], hours[-1] + timedelta(hours=1)
        results = []
        for eva, name in self._stations.items():
            try:
                xml = call_with_retries(lambda: self._client.full_changes(eva), sleep=self._sleep)
                self._archive(eva, "fchg", now, xml)
                planned = [s for stops in self._plans.get(eva, {}).values() for s in stops]
                stops = [
                    s
                    for s in merge(planned, parse_timetable(xml).stops)
                    if s.planned_time and start <= s.planned_time < end
                ]
                with self._session_factory() as session:
                    saved = upsert_stops(session, eva, name, stops)
                    session.commit()
            except Exception as exc:  # one broken station must not stop the others
                error = str(exc) or type(exc).__name__
                logger.warning("changes %s (%s) failed: %s", name, eva, error)
                results.append(CycleResult(eva, error=error))
                continue
            logger.info("changes %s (%s): %d stops saved", name, eva, saved)
            results.append(CycleResult(eva, stops_saved=saved))
        return results

    def _archive(self, eva: str, kind: str, fetched_at: datetime, xml: str) -> None:
        """Archiving is best effort: a full or unwritable disk must not lose data."""
        if self._archive_dir is None:
            return
        try:
            archive_response(self._archive_dir, eva, kind, fetched_at, xml)
        except Exception as exc:
            logger.warning("archiving %s for %s failed: %s", kind, eva, exc)


def _hour_start(moment: datetime) -> datetime:
    """Whole hour containing ``moment``, in UTC (Berlin offsets are whole hours)."""
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
