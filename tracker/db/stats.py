"""Delay statistics straight from stop_events. Week 3, task A.

All functions count only stops with planned_time in [start, end) and planned_time < now.
``start``/``end``/``now`` are timezone-aware datetimes; the API layer turns Berlin dates into them.
Aggregation runs in SQL (GROUP BY), not in Python, and must give the same results on
SQLite (tests) and PostgreSQL (production): use the precomputed integer columns
``hour_berlin``/``delay_minutes`` rather than dialect-specific time functions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tracker.api.schemas import HourStats, LineStats, StationStats


def station_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None,
) -> list[StationStats]:
    """One row per station (optionally only ``eva`` / only stops of ``line``), worst avg delay first."""
    raise NotImplementedError  # week 3, task A


def line_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None, limit: int | None = None,
) -> list[LineStats]:
    """One row per line (optionally only at ``eva`` / only ``line``), worst avg delay first."""
    raise NotImplementedError  # week 3, task A


def hour_stats(
    session: Session, start: datetime, end: datetime, now: datetime, *, eva: str | None = None,
    line: str | None = None,
) -> list[HourStats]:
    """One row per Berlin hour of day that has stops, ascending."""
    raise NotImplementedError  # week 3, task A
