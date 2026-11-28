"""Stats routes. Stats functions are imported by name so tests can replace them."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tracker.api.deps import BERLIN, PeriodRange, get_clock, get_period, get_session
from tracker.api.schemas import (
    ConnectionSearch,
    DelaySummary,
    LineDetail,
    LineList,
    Period,
    StationDetail,
    StationList,
    StationStats,
)
from tracker.db.stats import hour_stats, line_stats, station_stats
from tracker.routing.search import WINDOW_HOURS, search_connections
from tracker.stations import STATIONS

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
PeriodDep = Annotated[PeriodRange, Depends(get_period)]
CONNECTION_DAYS = 28
_HHMM = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")


def get_connection_period(
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    from_: Annotated[date | None, Query(alias="from", description="First day (Europe/Berlin), inclusive")] = None,
    to: Annotated[date | None, Query(description="Last day (Europe/Berlin), inclusive")] = None,
) -> PeriodRange:
    """Like ``get_period`` (same validation), but the default is the last 28 days."""
    last = to or clock().astimezone(BERLIN).date()
    first = from_ or last - timedelta(days=CONNECTION_DAYS - 1)
    return get_period(clock, first, last)


ConnectionPeriodDep = Annotated[PeriodRange, Depends(get_connection_period)]


def _period(p: PeriodRange) -> Period:
    return Period(start=p.first, end=p.last)


@router.get("/health", summary="Liveness check", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/stations", summary="All stations, worst delay first", tags=["stats"])
def stations(session: SessionDep, p: PeriodDep) -> StationList:
    rows = station_stats(session, p.start, p.end, p.now)
    return StationList(period=_period(p), stations=rows)


@router.get("/stations/{eva}", summary="One station: by hour and worst lines", tags=["stats"])
def station_detail(eva: str, session: SessionDep, p: PeriodDep) -> StationDetail:
    if eva not in STATIONS:
        raise HTTPException(404, f"Unknown station {eva}")
    rows = station_stats(session, p.start, p.end, p.now, eva=eva)
    station = rows[0] if rows else StationStats(
        eva=eva, name=STATIONS[eva], stops=0, cancelled=0, on_time_share=None, avg_delay_minutes=None
    )
    return StationDetail(
        period=_period(p),
        station=station,
        by_hour=hour_stats(session, p.start, p.end, p.now, eva=eva),
        worst_lines=line_stats(session, p.start, p.end, p.now, eva=eva, limit=5),
    )


@router.get("/lines", summary="All lines, worst delay first", tags=["stats"])
def lines(session: SessionDep, p: PeriodDep) -> LineList:
    return LineList(period=_period(p), lines=line_stats(session, p.start, p.end, p.now))


@router.get("/lines/{line}", summary="One line: by station and hour", tags=["stats"])
def line_detail(line: str, session: SessionDep, p: PeriodDep) -> LineDetail:
    rows = line_stats(session, p.start, p.end, p.now, line=line)
    if not rows or rows[0].stops == 0:
        raise HTTPException(404, f"No stops for line {line!r} in this period")
    return LineDetail(
        period=_period(p),
        line=line,
        summary=DelaySummary(**rows[0].model_dump(exclude={"line"})),
        by_station=station_stats(session, p.start, p.end, p.now, line=line),
        by_hour=hour_stats(session, p.start, p.end, p.now, line=line),
    )


@router.get(
    "/connections",
    summary="Most reliable connections between two stations",
    tags=["connections"],
)
def connections(
    session: SessionDep,
    p: ConnectionPeriodDep,
    from_eva: Annotated[str, Query(description="Start station EVA number")],
    to_eva: Annotated[str, Query(description="Destination station EVA number")],
    depart_after: Annotated[str, Query(description="Earliest departure, HH:MM Europe/Berlin")],
    day: Annotated[Literal["weekday", "weekend"] | None, Query(description="Day type; default: today")] = None,
) -> ConnectionSearch:
    for eva in (from_eva, to_eva):
        if eva not in STATIONS:
            raise HTTPException(404, f"Unknown station {eva}")
    if from_eva == to_eva:
        raise HTTPException(422, "'from_eva' and 'to_eva' must differ")
    m = _HHMM.fullmatch(depart_after)
    if not m:
        raise HTTPException(422, "'depart_after' must be HH:MM (00:00-23:59)")
    depart = time(int(m[1]), int(m[2]))
    day_type = day or ("weekend" if p.now.astimezone(BERLIN).weekday() >= 5 else "weekday")
    options = search_connections(
        session, from_eva, to_eva, depart, day_type, p.start, p.end, p.now
    )
    message = None
    if not options:
        end_hour = (depart.hour + WINDOW_HOURS) % 24
        message = (
            f"No connection between {STATIONS[from_eva]} and {STATIONS[to_eva]} departing "
            f"{depart_after}-{end_hour:02d}:{depart.minute:02d} on "
            f"{'weekdays' if day_type == 'weekday' else 'weekends'} in the observed data."
        )
    return ConnectionSearch(
        period=_period(p),
        from_eva=from_eva,
        from_name=STATIONS[from_eva],
        to_eva=to_eva,
        to_name=STATIONS[to_eva],
        depart_after=depart_after,
        day_type=day_type,
        options=options,
        message=message,
    )
