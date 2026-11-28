"""Response shapes of the stats API. Shared contract for tracker/db/stats.py and tracker/api/.

Definitions (DB's own): a stop counts as on time when its delay is under 6 minutes.
Only stops whose planned time lies in the requested period AND in the past are counted, and only
if the collector saw them at or after their planned time (``updated_at >= planned_time``): a stop
missed while the collector was paused keeps a stale prediction and would look on time.
A stop's delay is its departure delay, or its arrival delay if the train ends there.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

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


# --- Week 4: most reliable connection -------------------------------------------------------
# Built from history: trains are linked across stations by DB's trip id (stop_id without its
# last "-<n>" part; that last number is the stop's order in the trip). A "service" is one line
# leaving station A at the same planned time of day and reaching station B; its numbers come
# from every observed past run in the period, split by day type (weekday / weekend).


class ConnectionLeg(BaseModel):
    line: str
    from_eva: str
    from_name: str
    to_eva: str
    to_name: str
    departure: str = Field(description="Planned departure at from_eva, HH:MM Europe/Berlin")
    arrival: str = Field(description="Planned arrival at to_eva, HH:MM Europe/Berlin")
    runs: int = Field(description="Observed past runs this leg is based on (at least 3)")
    avg_arrival_delay_minutes: float | None = Field(description="Mean arrival delay of runs that ran")
    on_time_share: float | None = Field(description="Share of runs that ran and arrived under 6 min late")
    cancelled_share: float = Field(description="Share of runs cancelled on this leg")


class ConnectionOption(BaseModel):
    legs: list[ConnectionLeg]
    transfers: int
    transfer_minutes: list[int] = Field(description="Planned slack at each transfer station, 5 to 120 minutes")
    planned_departure: str
    planned_arrival: str
    planned_duration_minutes: int
    missed_transfer_share: float | None = Field(
        description="Share of first-leg runs too late for the transfer; null for direct trains"
    )
    expected_arrival_delay_minutes: float = Field(
        description=(
            "Expected delay at the destination: after a missed transfer, the wait for the next "
            "train; for a cancelled train, a flat 60-minute penalty"
        )
    )
    on_time_share: float | None = Field(description="Chance to reach the destination under 6 min late")


class ConnectionSearch(BaseModel):
    period: Period = Field(description="History used for the numbers")
    from_eva: str
    from_name: str
    to_eva: str
    to_name: str
    depart_after: str = Field(description=(
            "HH:MM Europe/Berlin; options depart within 3 hours after. Trains after midnight "
            "use the same day type"
        ))
    day_type: Literal["weekday", "weekend"]
    options: list[ConnectionOption] = Field(description="Best first (earliest expected arrival), at most 3")
    message: str | None = Field(default=None, description="Why options is empty, if it is")
