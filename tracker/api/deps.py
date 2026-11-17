"""Request dependencies: DB session, clock and the requested period."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

BERLIN = ZoneInfo("Europe/Berlin")
DEFAULT_DAYS = 7
MAX_DAYS = 92


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, closed afterwards."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_clock(request: Request) -> Callable[[], datetime]:
    return request.app.state.clock


@dataclass(frozen=True)
class PeriodRange:
    """Inclusive Berlin dates plus the aware [start, end) datetimes and ``now``."""

    first: date
    last: date
    start: datetime
    end: datetime
    now: datetime


def get_period(
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    from_: Annotated[date | None, Query(alias="from", description="First day (Europe/Berlin), inclusive")] = None,
    to: Annotated[date | None, Query(description="Last day (Europe/Berlin), inclusive")] = None,
) -> PeriodRange:
    """Validate ``from``/``to``; default is the last 7 days ending today (Berlin)."""
    now = clock()
    today = now.astimezone(BERLIN).date()
    last = to or today
    first = from_ or last - timedelta(days=DEFAULT_DAYS - 1)
    if first > today or last > today:
        raise HTTPException(422, "Dates in the future are not allowed")
    if first > last:
        raise HTTPException(422, "'from' must not be after 'to'")
    if (last - first).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"Period must not exceed {MAX_DAYS} days")
    return PeriodRange(
        first=first,
        last=last,
        start=datetime.combine(first, time.min, tzinfo=BERLIN),
        end=datetime.combine(last + timedelta(days=1), time.min, tzinfo=BERLIN),
        now=now,
    )
