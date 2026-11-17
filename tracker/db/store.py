from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.collector.parser import BERLIN, Event, Stop
from tracker.db.models import StopEvent

_NONE = Event()


def upsert_stops(session: Session, eva: str, station: str, stops: Sequence[Stop]) -> int:
    """Insert new stop events and update known ones. Returns how many were written.

    The caller commits.
    """
    existing = {
        row.stop_id: row
        for row in session.scalars(
            select(StopEvent).where(
                StopEvent.eva == eva,
                StopEvent.stop_id.in_([stop.stop_id for stop in stops]),
            )
        )
    }
    # Berlin-aware so SQLite (wall time) compares updated_at with planned_time consistently.
    now = datetime.now(UTC).astimezone(BERLIN)
    for stop in stops:
        row = existing.get(stop.stop_id)
        if row is None:
            row = existing[stop.stop_id] = StopEvent(eva=eva, stop_id=stop.stop_id)
            session.add(row)
        _fill(row, station, stop, now)
    return len(stops)


def _fill(row: StopEvent, station: str, stop: Stop, now: datetime) -> None:
    arrival = stop.arrival or _NONE
    departure = stop.departure or _NONE
    row.station = station
    row.category = stop.category
    row.number = stop.number
    row.line = stop.line_name or None
    row.planned_arrival = arrival.planned_time
    row.changed_arrival = arrival.changed_time
    row.planned_departure = departure.planned_time
    row.changed_departure = departure.changed_time
    row.planned_platform = departure.planned_platform or arrival.planned_platform
    row.changed_platform = departure.changed_platform or arrival.changed_platform
    row.cancelled = stop.cancelled
    row.updated_at = now
    row.planned_time = stop.planned_time
    row.delay_minutes = stop.delay_minutes
    local = stop.planned_time.astimezone(BERLIN) if stop.planned_time else None
    row.hour_berlin = local.hour if local else None
    row.weekday_berlin = local.weekday() if local else None
