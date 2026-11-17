"""Stats routes. Stats functions are imported by name so tests can replace them."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tracker.api.deps import PeriodRange, get_period, get_session
from tracker.api.schemas import (
    DelaySummary,
    LineDetail,
    LineList,
    Period,
    StationDetail,
    StationList,
    StationStats,
)
from tracker.db.stats import hour_stats, line_stats, station_stats
from tracker.stations import STATIONS

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
PeriodDep = Annotated[PeriodRange, Depends(get_period)]


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
