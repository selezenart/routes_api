"""Turn XML from the DB Timetables API into plain Python objects.

Both the planned timetable (``/plan``) and the change feeds (``/fchg``, ``/rchg``)
use the same shape: a ``<timetable>`` with one ``<s>`` per train stop, holding an
optional train label ``<tl>``, an arrival ``<ar>`` and a departure ``<dp>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from defusedxml.ElementTree import fromstring

BERLIN = ZoneInfo("Europe/Berlin")
TIME_FORMAT = "%y%m%d%H%M"  # e.g. 2611131204 = 13 Nov 2026, 12:04


@dataclass(frozen=True)
class Event:
    """One arrival or departure of a train at a station."""

    planned_time: datetime | None = None
    changed_time: datetime | None = None
    planned_platform: str | None = None
    changed_platform: str | None = None
    line: str | None = None
    status: str | None = None  # "p" planned, "a" added, "c" cancelled

    @property
    def cancelled(self) -> bool:
        return self.status == "c"

    @property
    def delay_minutes(self) -> int | None:
        """Minutes late. No known change means on time; no planned time means unknown."""
        if self.planned_time is None:
            return None
        if self.changed_time is None:
            return 0
        return int((self.changed_time - self.planned_time).total_seconds() // 60)


@dataclass(frozen=True)
class Stop:
    """One train stopping at one station: its arrival and/or departure."""

    stop_id: str
    category: str | None = None  # RE, ICE, S, ...
    number: str | None = None  # train number, e.g. 19412
    arrival: Event | None = None
    departure: Event | None = None

    @property
    def main_event(self) -> Event | None:
        """The departure if the train leaves here, otherwise the arrival."""
        return self.departure or self.arrival

    @property
    def planned_time(self) -> datetime | None:
        return self.main_event.planned_time if self.main_event else None

    @property
    def delay_minutes(self) -> int | None:
        return self.main_event.delay_minutes if self.main_event else None

    @property
    def cancelled(self) -> bool:
        return any(e.cancelled for e in (self.arrival, self.departure) if e)

    @property
    def train_name(self) -> str:
        return " ".join(p for p in (self.category, self.number) if p)

    @property
    def line_name(self) -> str:
        """Line as shown on the board, e.g. "RE8" or "S 4". Falls back to the train number.

        DB usually sends the line with its prefix ("RE8", "MEX18"), sometimes just a
        number ("4" for an S-Bahn), and long-distance trains often have no line at all.
        """
        line = next((e.line for e in (self.departure, self.arrival) if e and e.line), None)
        if line and line[0].isalpha():
            return line
        return " ".join(p for p in (self.category, line or self.number) if p)


@dataclass(frozen=True)
class Timetable:
    station: str | None
    stops: list[Stop] = field(default_factory=list)


@dataclass(frozen=True)
class Station:
    name: str
    eva: str


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=BERLIN)


def parse_timetable(xml: str | bytes) -> Timetable:
    root = fromstring(xml)
    stops = [_parse_stop(s) for s in root.findall("s")]
    return Timetable(station=root.get("station"), stops=stops)


def parse_stations(xml: str | bytes) -> list[Station]:
    root = fromstring(xml)
    return [Station(name=s.get("name", ""), eva=s.get("eva", "")) for s in root.findall("station")]


def _parse_stop(element) -> Stop:
    label = element.find("tl")
    return Stop(
        stop_id=element.get("id", ""),
        category=label.get("c") if label is not None else None,
        number=label.get("n") if label is not None else None,
        arrival=_parse_event(element.find("ar")),
        departure=_parse_event(element.find("dp")),
    )


def _parse_event(element) -> Event | None:
    if element is None:
        return None
    return Event(
        planned_time=parse_time(element.get("pt")),
        changed_time=parse_time(element.get("ct")),
        planned_platform=element.get("pp"),
        changed_platform=element.get("cp"),
        line=element.get("l"),
        status=element.get("cs") or element.get("ps"),
    )
