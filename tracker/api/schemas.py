"""Response shapes of the stats API. Shared contract for tracker/db/stats.py and tracker/api/.

Definitions (DB's own): a stop counts as on time when its delay is under 6 minutes.
Only stops whose planned time lies in the requested period AND in the past are counted.
A stop's delay is its departure delay, or its arrival delay if the train ends there.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DelaySummary(BaseModel):
    stops: int = Field(description="Stop events counted, cancelled ones included")
    cancelled: int
    on_time_share: float | None = Field(
        description="Share of non-cancelled stops under 6 minutes late, 0..1; null if none"
    )
    avg_delay_minutes: float | None = Field(description="Mean delay of non-cancelled stops; null if none")


class HourStats(DelaySummary):
    hour: int = Field(ge=0, le=23, description="Hour of day in Europe/Berlin")


class LineStats(DelaySummary):
    line: str = Field(description='Line as on the board, e.g. "RE8" or "ICE 512"')


class StationStats(DelaySummary):
    eva: str
    name: str


class Period(BaseModel):
    start: date = Field(description="First day, Europe/Berlin, inclusive")
    end: date = Field(description="Last day, Europe/Berlin, inclusive")


class StationDetail(BaseModel):
    period: Period
    station: StationStats
    by_hour: list[HourStats] = Field(description="Only hours that have stops, ascending")
    worst_lines: list[LineStats] = Field(description="Highest avg delay first")


class LineDetail(BaseModel):
    period: Period
    line: str
    summary: DelaySummary
    by_station: list[StationStats] = Field(description="Highest avg delay first")
    by_hour: list[HourStats]


class StationList(BaseModel):
    period: Period
    stations: list[StationStats] = Field(description="Highest avg delay first")


class LineList(BaseModel):
    period: Period
    lines: list[LineStats] = Field(description="Highest avg delay first")
