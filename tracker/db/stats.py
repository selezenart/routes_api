"""Delay statistics straight from stop_events. Week 3, task A.

All functions count only stops with planned_time in [start, end) and planned_time < now
that were observed: ``updated_at >= planned_time`` (the collector polled them after they were due;
otherwise the delay is just the last prediction).
``start``/``end``/``now`` are timezone-aware datetimes; the API layer turns Berlin dates into them.
Aggregation runs in SQL (GROUP BY), not in Python, and must give the same results on
SQLite (tests) and PostgreSQL (production): use the precomputed integer columns
``hour_berlin``/``delay_minutes`` rather than dialect-specific time functions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from tracker.api.schemas import HourStats, LineStats, StationStats
from tracker.collector.parser import BERLIN
from tracker.db.models import StopEvent as S

LATE_MINUTES = 6  # same threshold as tracker.cli.LATE_MINUTES

_ok = S.cancelled.is_(False)
_STOPS = func.count()
_CANCELLED = func.coalesce(func.sum(case((S.cancelled, 1), else_=0)), 0)
_JUDGED = func.sum(case((_ok, 1), else_=0))
_ON_TIME = func.sum(case((_ok & (S.delay_minutes < LATE_MINUTES), 1), else_=0))
_AVG = func.avg(case((_ok, S.delay_minutes)))


def _summary(row) -> dict:
    judged = row.judged or 0
    return {
        "stops": row.stops,
        "cancelled": int(row.cancelled),
        "on_time_share": (row.on_time or 0) / judged if judged else None,
        "avg_delay_minutes": round(float(row.avg_delay), 1) if row.avg_delay is not None else None,
    }


def _query(*group_cols, start, end, now, eva, line, extra=()) -> Select:
    # Bind Berlin-local datetimes: SQLite keeps wall time and drops the offset.
    start, end, now = (t.astimezone(BERLIN) for t in (start, end, now))
    query = select(
        *group_cols,
        *extra,
        _STOPS.label("stops"),
        _CANCELLED.label("cancelled"),
        _JUDGED.label("judged"),
        _ON_TIME.label("on_time"),
        _AVG.label("avg_delay"),
    ).where(
        S.planned_time >= start, S.planned_time < end, S.planned_time < now, S.updated_at >= S.planned_time
    )
    if eva is not None:
        query = query.where(S.eva == eva)
    if line is not None:
        query = query.where(S.line == line)
    return query.group_by(*group_cols)


def _worst_first(query: Select, *tiebreak) -> Select:
    # avg is NULL when nothing was judged: sort those last on every dialect.
    return query.order_by(_AVG.is_(None), _AVG.desc(), *tiebreak)


def station_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None,
) -> list[StationStats]:
    """One row per station (optionally only ``eva`` / only stops of ``line``), worst avg delay first."""
    name = func.max(S.station).label("station")  # a renamed station still gives one row per eva
    query = _query(S.eva, extra=(name,), start=start, end=end, now=now, eva=eva, line=line)
    query = _worst_first(query, name, S.eva)
    return [StationStats(eva=r.eva, name=r.station, **_summary(r)) for r in session.execute(query)]


def line_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None, limit: int | None = None,
) -> list[LineStats]:
    """One row per line (optionally only at ``eva`` / only ``line``), worst avg delay first."""
    query = _query(S.line, start=start, end=end, now=now, eva=eva, line=line)
    query = _worst_first(query.where(S.line.is_not(None)), S.line)
    if limit is not None:
        query = query.limit(limit)
    return [LineStats(line=r.line, **_summary(r)) for r in session.execute(query)]


def hour_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None,
) -> list[HourStats]:
    """One row per Berlin hour of day that has stops, ascending."""
    query = _query(S.hour_berlin, start=start, end=end, now=now, eva=eva, line=line)
    query = query.where(S.hour_berlin.is_not(None)).order_by(S.hour_berlin)
    return [HourStats(hour=r.hour_berlin, **_summary(r)) for r in session.execute(query)]
