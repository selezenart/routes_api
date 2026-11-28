"""Most reliable connection between two collected stations. Week 4, task A.

Pipeline: load observed past stop events in the period, link them into leg runs by trip id
(same trip, earlier stop order at A than at B), group runs into services (line, A, B, planned
departure time of day, day type), then search the station graph for direct and one-transfer
connections (DFS over stations, as in the original route finder in src/routes/utils.py).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.api.schemas import ConnectionLeg, ConnectionOption
from tracker.collector.parser import BERLIN
from tracker.db.models import StopEvent as S
from tracker.stations import STATIONS

MIN_TRANSFER_MINUTES = 5
MAX_TRANSFER_MINUTES = 120  # longer waits are not a sensible transfer
MIN_RUNS = 3  # services seen fewer times are too thin to rank on
WINDOW_HOURS = 3
MISSED_TRANSFER_PENALTY_MINUTES = 60  # when no later train to wait for is known
LATE_MINUTES = 6  # same threshold as tracker.db.stats
DAY = 24 * 60

DayType = Literal["weekday", "weekend"]


@dataclass(frozen=True)
class Run:
    """One train going from A to B once."""

    trip: str
    line: str
    from_eva: str
    to_eva: str
    departure: datetime
    arrival: datetime
    arrival_delay: int | None  # None: cancelled at A or B


@dataclass
class Service:
    """Runs of one line from A to B at the same planned time of day and day type."""

    line: str
    from_eva: str
    to_eva: str
    dep_min: int  # planned departure, minutes since midnight (Berlin)
    duration: int  # planned minutes A -> B
    day_type: DayType
    delays: list[int] = field(default_factory=list)  # arrival delays of runs that ran
    cancelled: int = 0
    trips: set[str] = field(default_factory=set)

    @property
    def runs(self) -> int:
        return len(self.delays) + self.cancelled

    @property
    def arr_min(self) -> int:
        return self.dep_min + self.duration  # may pass 1440

    @property
    def avg_delay(self) -> float | None:
        return sum(self.delays) / len(self.delays) if self.delays else None

    @property
    def cancelled_share(self) -> float:
        return self.cancelled / self.runs

    @property
    def on_time_share(self) -> float:
        return sum(d < LATE_MINUTES for d in self.delays) / self.runs

    @property
    def expected_delay(self) -> float:
        """Mean delay at B; a cancelled run costs the missed-transfer penalty."""
        c = self.cancelled_share
        return (1 - c) * (self.avg_delay or 0.0) + c * MISSED_TRANSFER_PENALTY_MINUTES


def _berlin(t: datetime) -> datetime:
    """SQLite returns naive Berlin wall time, PostgreSQL aware datetimes."""
    return t.replace(tzinfo=BERLIN) if t.tzinfo is None else t.astimezone(BERLIN)


def _day_type(t: datetime) -> DayType:
    return "weekday" if t.weekday() < 5 else "weekend"


def _hm(minutes: int) -> str:
    minutes %= DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _split_id(stop_id: str) -> tuple[str, int] | None:
    trip, _, order = stop_id.rpartition("-")
    return (trip, int(order)) if trip and order.isdigit() else None


def _minutes(planned: datetime, changed: datetime | None) -> int:
    return 0 if changed is None else int((changed - planned).total_seconds() // 60)


def load_runs(session: Session, start: datetime, end: datetime, now: datetime) -> list[Run]:
    """Observed past leg runs between collected stations, linked by trip id.

    A stop counts when its planned_time (departure, else arrival) is in the period and observed,
    like in tracker/db/stats.py. So a middle stop B, which has a departure, is filtered by its
    departure time, not its arrival.
    """
    start, end, now = (t.astimezone(BERLIN) for t in (start, end, now))
    rows = session.execute(
        select(
            S.eva, S.stop_id, S.line, S.cancelled, S.planned_arrival, S.changed_arrival,
            S.planned_departure,
        ).where(
            S.eva.in_(list(STATIONS)),
            S.planned_time >= start, S.planned_time < end, S.planned_time < now,
            S.updated_at >= S.planned_time,
        )
    )
    trips: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for row in rows:
        if (parts := _split_id(row.stop_id)) is not None:
            trips[parts[0]].append((parts[1], row))
    runs = []
    for trip, stops in trips.items():
        stops.sort(key=lambda item: item[0])
        for i, (order_a, a) in enumerate(stops):
            if a.planned_departure is None:
                continue
            for order_b, b in stops[i + 1:]:
                if order_b == order_a or b.eva == a.eva or b.planned_arrival is None:
                    continue
                dep, arr = _berlin(a.planned_departure), _berlin(b.planned_arrival)
                if arr.astimezone(UTC) <= dep.astimezone(UTC):
                    continue
                delay = None
                if not (a.cancelled or b.cancelled):
                    delay = _minutes(b.planned_arrival, b.changed_arrival)
                runs.append(Run(trip, a.line or b.line or "?", a.eva, b.eva, dep, arr, delay))
    return runs


def build_services(runs: list[Run]) -> list[Service]:
    """Group runs by (line, A, B, departure HH:MM, arrival HH:MM, day type)."""
    services: dict[tuple, Service] = {}
    for run in runs:
        dep_min = run.departure.hour * 60 + run.departure.minute
        # elapsed minutes on UTC instants: wall-clock subtraction is wrong across DST changes
        duration = int((run.arrival.astimezone(UTC) - run.departure.astimezone(UTC)).total_seconds() // 60)
        arr_wall = run.arrival.hour * 60 + run.arrival.minute
        key = (run.line, run.from_eva, run.to_eva, dep_min, arr_wall,
               _day_type(run.departure))
        service = services.get(key)
        if service is None:
            service = services[key] = Service(run.line, run.from_eva, run.to_eva, dep_min,
                                              duration, key[-1])
        service.trips.add(run.trip)
        if run.arrival_delay is None:
            service.cancelled += 1
        else:
            service.delays.append(run.arrival_delay)
    return list(services.values())


def _slack(first: Service, second: Service) -> int:
    """Planned minutes between arriving with ``first`` and leaving with ``second``."""
    return (second.dep_min - first.arr_min) % DAY


def _chains(
    services: list[Service], from_eva: str, to_eva: str, rel_start: int, max_transfers: int
) -> list[list[Service]]:
    """DFS over stations: every leg chain from ``from_eva`` to ``to_eva``, never revisiting."""
    leaving: dict[str, list[Service]] = defaultdict(list)
    for s in services:
        leaving[s.from_eva].append(s)

    found: list[list[Service]] = []

    def walk(station: str, visited: set[str], chain: list[Service]) -> None:
        for s in leaving[station]:
            if chain:
                if not MIN_TRANSFER_MINUTES <= _slack(chain[-1], s) <= MAX_TRANSFER_MINUTES:
                    continue
                if chain[-1].trips & s.trips:  # same train: stay on board, that is direct
                    continue
            elif (s.dep_min - rel_start) % DAY >= WINDOW_HOURS * 60:
                continue
            if s.to_eva == to_eva:
                found.append([*chain, s])
            elif s.to_eva not in visited and len(chain) < max_transfers:
                walk(s.to_eva, visited | {s.to_eva}, [*chain, s])

    walk(from_eva, {from_eva}, [])
    return found


ServiceIndex = dict[tuple[str, str, DayType], list[Service]]


def index_services(services: list[Service]) -> ServiceIndex:
    """Services per (from, to, day type), sorted by planned departure."""
    index: ServiceIndex = defaultdict(list)
    for s in sorted(services, key=lambda s: s.dep_min):
        index[(s.from_eva, s.to_eva, s.day_type)].append(s)
    return index


def _miss_cost(index: ServiceIndex, first: Service, chosen: Service) -> float:
    """Minutes lost after missing ``chosen``: wait for the next later service, else penalty.

    The next service must leave at least MIN_TRANSFER_MINUTES after the first leg's planned
    arrival plus its average delay, so it is one the late first leg can actually catch.
    """
    earliest = first.arr_min + (first.avg_delay or 0.0) + MIN_TRANSFER_MINUTES
    later = [
        s for s in index[(chosen.from_eva, chosen.to_eva, chosen.day_type)]
        if s.dep_min != chosen.dep_min and (s.dep_min - first.arr_min) % DAY >= earliest - first.arr_min
    ]
    if not later:
        return MISSED_TRANSFER_PENALTY_MINUTES
    nxt = min(later, key=lambda s: (s.dep_min - chosen.dep_min) % DAY)
    wait = (nxt.dep_min - chosen.dep_min) % DAY + nxt.duration - chosen.duration
    return min(wait + (nxt.avg_delay or 0.0), MISSED_TRANSFER_PENALTY_MINUTES)


def _leg(s: Service) -> ConnectionLeg:
    return ConnectionLeg(
        line=s.line, from_eva=s.from_eva, from_name=STATIONS[s.from_eva],
        to_eva=s.to_eva, to_name=STATIONS[s.to_eva],
        departure=_hm(s.dep_min), arrival=_hm(s.arr_min), runs=s.runs,
        avg_arrival_delay_minutes=None if s.avg_delay is None else round(s.avg_delay, 1),
        on_time_share=round(s.on_time_share, 3), cancelled_share=round(s.cancelled_share, 3),
    )


@dataclass
class Scored:
    option: ConnectionOption
    expected_arrival: float  # minutes after depart_after, so midnight crossings sort right
    on_time: float
    depart_offset: int = 0  # minutes after depart_after


def score(index: ServiceIndex, chain: list[Service], rel_start: int) -> Scored:
    """Numbers for one direct or one-transfer chain.

    Independence is assumed: a miss on the first leg and a delay or cancellation on the second
    leg are treated as unrelated, so on_time_share = (1 - miss) * second leg on_time_share.
    Missing the transfer costs the wait for the next later service (or the penalty).
    """
    first, last = chain[0], chain[-1]
    miss: float | None = None
    slacks: list[int] = []
    expected, on_time = last.expected_delay, last.on_time_share
    if len(chain) == 2:
        slack = _slack(first, last)
        slacks = [slack]
        late = first.cancelled + sum(d > slack - MIN_TRANSFER_MINUTES for d in first.delays)
        miss = late / first.runs
        expected = (1 - miss) * expected + miss * _miss_cost(index, first, last)
        on_time *= 1 - miss
    duration = sum(s.duration for s in chain) + sum(slacks)
    option = ConnectionOption(
        legs=[_leg(s) for s in chain], transfers=len(chain) - 1, transfer_minutes=slacks,
        planned_departure=_hm(first.dep_min), planned_arrival=_hm(first.dep_min + duration),
        planned_duration_minutes=duration,
        missed_transfer_share=None if miss is None else round(miss, 3),
        expected_arrival_delay_minutes=round(expected, 1), on_time_share=round(on_time, 3),
    )
    return Scored(option, (first.dep_min - rel_start) % DAY + duration + expected, on_time,
                  (first.dep_min - rel_start) % DAY)


def search_connections(
    session: Session,
    from_eva: str,
    to_eva: str,
    depart_after: time,
    day_type: Literal["weekday", "weekend"],
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    max_transfers: int = 1,
    limit: int = 3,
) -> list[ConnectionOption]:
    """Up to ``limit`` options leaving ``from_eva`` within WINDOW_HOURS after ``depart_after``.

    Ranked by expected arrival (planned arrival + expected delay), ties by higher on_time_share.
    Only stops observed at or after their planned time count (as in tracker/db/stats.py).
    Services with fewer than MIN_RUNS observed runs are ignored. Per last-leg service and
    transfer station only the best chain is kept, so one second train cannot fill the list.
    Services leaving after midnight inside the window still use the requested ``day_type``.
    Transfers wait between MIN_TRANSFER_MINUTES and MAX_TRANSFER_MINUTES (planned slack).
    """
    if max_transfers > 1:
        raise ValueError("only direct and one-transfer connections are supported")
    services = [
        s for s in build_services(load_runs(session, start, end, now))
        if s.day_type == day_type and s.runs >= MIN_RUNS
    ]
    index = index_services(services)
    rel_start = depart_after.hour * 60 + depart_after.minute
    best: dict[tuple, Scored] = {}
    for chain in _chains(services, from_eva, to_eva, rel_start, max_transfers):
        sc = score(index, chain, rel_start)
        # one train must not fill the list: keep the best way to reach each last-leg service
        key = (id(chain[-1]), chain[0].to_eva if len(chain) == 2 else None)
        if key not in best or _better(sc, best[key]):
            best[key] = sc
    scored = sorted(best.values(), key=lambda sc: (sc.expected_arrival, -sc.on_time, sc.option.transfers))
    return [sc.option for sc in scored[:limit]]


def _better(new: Scored, old: Scored) -> bool:
    """Same last leg and transfer station: higher on_time, then later first departure, then fewer transfers."""
    return (new.on_time, new.depart_offset, -new.option.transfers) > (
        old.on_time, old.depart_offset, -old.option.transfers)
