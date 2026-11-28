"""Connection search on in-memory SQLite, history built with upsert_stops."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from tracker.collector.parser import BERLIN, Event, Stop
from tracker.db.models import StopEvent
from tracker.db.session import create_schema, make_engine, make_session_factory
from tracker.db.store import upsert_stops
from tracker.routing import search as search_module
from tracker.routing.search import (
    Run,
    _berlin,
    MISSED_TRANSFER_PENALTY_MINUTES,
    build_services,
    load_runs,
    search_connections,
)

A, C, B = "8000157", "8000096", "8000261"  # Heilbronn, Stuttgart, Muenchen
START = datetime(2026, 11, 1, tzinfo=BERLIN)
END = datetime(2026, 11, 20, tzinfo=BERLIN)
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=BERLIN)
THU, FRI, SAT = (datetime(2026, 11, d, tzinfo=BERLIN) for d in (12, 13, 14))


def at(day: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m))


def ev(day, hhmm, late=0, line="RE1", cancelled=False):
    t = at(day, hhmm)
    return Event(planned_time=t, changed_time=t + timedelta(minutes=late) if late else None,
                 line=line, status="c" if cancelled else None)


@pytest.fixture(autouse=True)
def one_run_is_enough(monkeypatch):
    """Most tests build tiny histories; MIN_RUNS has its own tests."""
    monkeypatch.setattr(search_module, "MIN_RUNS", 1)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    with make_session_factory(engine)() as session:
        yield session


def train(session, trip, day, stops, line="RE1", observed_at=NOW):
    """stops: (eva, arrival hh:mm | None, departure hh:mm | None, arrival late[, cancelled])."""
    for i, (eva, arr, dep, late, *cancelled) in enumerate(stops, start=1):
        cancelled = bool(cancelled and cancelled[0])
        stop = Stop(
            stop_id=f"{trip}-{i}", category="RE", number=trip,
            arrival=ev(day, arr, late, line, cancelled) if arr else None,
            departure=ev(day, dep, 0, line, cancelled) if dep else None,
        )
        upsert_stops(session, eva, "x", [stop])
    for row in session.scalars(select(StopEvent).where(StopEvent.stop_id.like(f"{trip}-%"))):
        row.updated_at = observed_at
    session.commit()


def search(session, frm, to, after="08:00", day_type="weekday", **kw):
    h, m = after.split(":")
    return search_connections(session, frm, to, time(int(h), int(m)), day_type, START, END, NOW, **kw)


def direct(session, trip, day, dep="08:10", arr="09:10", late=0, line="RE1", cancelled=False):
    train(session, trip, day, [(A, None, dep, 0), (B, arr, None, late, cancelled)], line)


def lines(options):
    return [o.legs[0].line for o in options]


def test_direct_train_found(session):
    direct(session, "t1", THU)
    direct(session, "t2", FRI, late=4)
    [opt] = search(session, A, B)
    assert opt.transfers == 0 and opt.transfer_minutes == [] and opt.missed_transfer_share is None
    assert (opt.planned_departure, opt.planned_arrival, opt.planned_duration_minutes) == ("08:10", "09:10", 60)
    [leg] = opt.legs
    assert (leg.line, leg.from_name, leg.to_name, leg.runs) == ("RE1", "Heilbronn Hbf", "München Hbf", 2)
    assert leg.avg_arrival_delay_minutes == 2.0
    assert opt.expected_arrival_delay_minutes == 2.0 and opt.on_time_share == 1.0


def test_cancelled_runs_lower_on_time_share(session):
    direct(session, "t1", THU)
    direct(session, "t2", FRI, cancelled=True)
    [opt] = search(session, A, B)
    assert opt.legs[0].cancelled_share == 0.5
    assert opt.on_time_share == 0.5
    assert opt.expected_arrival_delay_minutes == pytest.approx(0.5 * MISSED_TRANSFER_PENALTY_MINUTES)


def test_late_edge_five_vs_six_minutes(session):
    direct(session, "t1", THU, late=5)
    direct(session, "t2", FRI, late=6)
    [opt] = search(session, A, B)
    assert opt.on_time_share == 0.5


def change(session, day, trip, first_late=0, second_dep="09:20", second_arr="10:20", second_line="RE2"):
    """A 08:10 -> C 09:00 (first leg), then C -> B on another train."""
    train(session, f"{trip}a", day, [(A, None, "08:10", 0), (C, "09:00", None, first_late)])
    train(session, f"{trip}b", day, [(C, None, second_dep, 0), (B, second_arr, None, 0)], second_line)


def test_one_transfer_found_via_middle_station(session):
    change(session, THU, "x")
    [opt] = search(session, A, B)
    assert opt.transfers == 1 and opt.transfer_minutes == [20]
    assert [leg.to_eva for leg in opt.legs] == [C, B]
    assert (opt.planned_departure, opt.planned_arrival, opt.planned_duration_minutes) == ("08:10", "10:20", 130)
    assert opt.missed_transfer_share == 0.0 and opt.on_time_share == 1.0


def test_too_tight_transfer_rejected(session):
    change(session, THU, "x", second_dep="09:04", second_arr="10:00")
    assert search(session, A, B) == []
    change(session, FRI, "y", second_dep="09:05", second_arr="10:00")
    [opt] = search(session, A, B)
    assert opt.transfer_minutes == [5]


def test_missed_transfer_share_from_first_leg_delays(session):
    # slack 20: arrival delay 15 is fine (5 min left), 16 misses; cancelled first leg misses
    change(session, THU, "a", first_late=15)
    change(session, FRI, "b", first_late=16)
    train(session, "cz", datetime(2026, 11, 5, tzinfo=BERLIN),
          [(A, None, "08:10", 0), (C, "09:00", None, 0, True)])
    change(session, datetime(2026, 11, 6, tzinfo=BERLIN), "d")
    [opt] = search(session, A, B)
    assert opt.missed_transfer_share == 0.5  # 2 of 4 runs
    assert opt.on_time_share == 0.5


def test_miss_cost_uses_next_later_service(session):
    change(session, THU, "x", first_late=30)  # always misses
    train(session, "n1", THU, [(C, None, "09:50", 0), (B, "10:50", None, 4)], "RE3")
    options = search(session, A, B, limit=10)
    opt = next(o for o in options if o.legs[1].line == "RE2")
    # next service arrives 10:50 vs 10:20 planned (+30) plus its avg delay 4
    assert opt.missed_transfer_share == 1.0
    assert opt.expected_arrival_delay_minutes == 34.0
    assert opt.on_time_share == 0.0


def test_miss_cost_penalty_without_later_service(session):
    change(session, THU, "x", first_late=30)
    [opt] = search(session, A, B)
    assert opt.expected_arrival_delay_minutes == MISSED_TRANSFER_PENALTY_MINUTES


def test_same_train_through_c_is_direct_not_transfer(session):
    train(session, "t", THU, [(A, None, "08:10", 0), (C, "09:00", "09:10", 0), (B, "10:00", None, 0)])
    options = search(session, A, B)
    assert [o.transfers for o in options] == [0]
    assert options[0].legs[0].departure == "08:10" and options[0].legs[0].arrival == "10:00"


def test_ranking_and_limit(session):
    direct(session, "slow", THU, dep="08:10", arr="09:10", late=20, line="RE1")  # 09:30
    direct(session, "fast", THU, dep="08:30", arr="09:20", line="ICE1")  # 09:20
    direct(session, "mid", FRI, dep="08:40", arr="09:20", late=7, line="RE9")  # 09:27
    assert lines(search(session, A, B, limit=10)) == ["ICE1", "RE9", "RE1"]
    assert lines(search(session, A, B, limit=2)) == ["ICE1", "RE9"]


def test_ties_prefer_higher_on_time_share(session):
    direct(session, "a", THU, dep="08:10", arr="09:10", line="RE1", late=2)
    direct(session, "b", FRI, dep="08:10", arr="09:10", line="RE1", late=4)
    direct(session, "c", THU, dep="08:00", arr="09:10", line="RE2", late=0)
    direct(session, "d", FRI, dep="08:00", arr="09:10", line="RE2", late=6)
    # RE1: expected delay 3, on time 1.0 -> 09:13; RE2: 3 as well, on time 0.5
    assert lines(search(session, A, B)) == ["RE1", "RE2"]


def test_window_bounds(session):
    direct(session, "in", THU, dep="10:59", arr="11:59", line="IN")
    direct(session, "out", THU, dep="11:00", arr="12:00", line="OUT")
    direct(session, "early", THU, dep="07:59", arr="08:59", line="EARLY")
    direct(session, "start", THU, dep="08:00", arr="09:00", line="START")
    assert sorted(lines(search(session, A, B, after="08:00", limit=10))) == ["IN", "START"]


def test_window_crossing_midnight(session):
    direct(session, "late", THU, dep="23:30", arr="23:50", line="LATE")
    direct(session, "early", THU, dep="01:10", arr="02:10", line="EARLY")
    direct(session, "noon", THU, dep="12:00", arr="13:00", line="NOON")
    assert lines(search(session, A, B, after="22:30", limit=10)) == ["LATE", "EARLY"]


def test_weekday_and_weekend_separate(session):
    direct(session, "wd", THU, line="WD")
    direct(session, "we", SAT, line="WE")
    assert lines(search(session, A, B, day_type="weekday")) == ["WD"]
    assert lines(search(session, A, B, day_type="weekend")) == ["WE"]


def test_unobserved_and_future_stops_ignored(session):
    direct(session, "t", THU)
    # polled before the train was due: only a prediction
    train(session, "u", FRI, [(A, None, "08:10", 0), (B, "09:10", None, 0)],
          observed_at=at(FRI, "07:00"))
    # planned after "now"
    train(session, "f", datetime(2026, 11, 26, tzinfo=BERLIN),
          [(A, None, "08:10", 0), (B, "09:10", None, 0)])
    [opt] = search(session, A, B)
    assert opt.legs[0].runs == 1


def test_outside_period_and_unknown_stations_ignored(session):
    direct(session, "old", datetime(2026, 10, 1, tzinfo=BERLIN))
    train(session, "x", THU, [(A, None, "08:10", 0), ("9999999", "09:10", None, 0)])
    assert search(session, A, B) == []
    assert search(session, A, "9999999") == []


def test_no_options_is_empty_and_wrong_direction_ignored(session):
    assert search(session, A, B) == []
    direct(session, "t", THU)
    assert search(session, B, A) == []


def test_never_revisits_station(session):
    train(session, "p", THU, [(A, None, "08:10", 0), (C, "09:00", None, 0)])
    train(session, "q", THU, [(C, None, "09:20", 0), (A, "10:00", None, 0)])
    train(session, "r", THU, [(A, None, "10:10", 0), (B, "11:00", None, 0)])
    options = search(session, A, B, after="08:00", limit=10)
    assert [o.transfers for o in options] == [0]  # A -> C -> A -> B is never built


def test_max_transfers_zero_and_unsupported(session):
    change(session, THU, "x")
    assert search(session, A, B, max_transfers=0) == []
    with pytest.raises(ValueError):
        search(session, A, B, max_transfers=2)


def test_load_runs_and_services(session):
    direct(session, "t1", THU)
    direct(session, "t2", FRI, late=3)
    runs = load_runs(session, START, END, NOW)
    assert len(runs) == 2 and {r.arrival_delay for r in runs} == {0, 3}
    [service] = build_services(runs)
    assert (service.dep_min, service.duration, service.day_type, service.runs) == (490, 60, "weekday", 2)


def test_min_runs_drops_thin_services(session, monkeypatch):
    monkeypatch.setattr(search_module, "MIN_RUNS", 3)
    direct(session, "a", THU, line="THIN")
    direct(session, "b", THU, line="THIN")
    for i, day in enumerate((THU, FRI, datetime(2026, 11, 16, tzinfo=BERLIN))):
        direct(session, f"c{i}", day, dep="08:20", arr="09:20", line="OK")
    assert lines(search(session, A, B)) == ["OK"]
    # a thin service is not a leg either
    change(session, THU, "x")
    assert [o.transfers for o in search(session, A, B)] == [0]


def test_one_second_train_cannot_fill_the_list(session):
    # three first trains all connect to the same C -> B train
    for i, dep in enumerate(("07:50", "08:10", "08:30")):
        train(session, f"f{i}", THU, [(A, None, dep, 0), (C, "09:00", None, 0)], f"F{i}")
    train(session, "s", THU, [(C, None, "09:20", 0), (B, "10:20", None, 0)], "RE2")
    direct(session, "d", THU, dep="08:40", arr="11:00", line="SLOW")
    options = search(session, A, B, limit=3)
    assert len(options) == 2
    via = [o for o in options if o.transfers == 1]
    assert len(via) == 1 and via[0].legs[0].line == "F2"  # same on time share: later departure


def test_miss_cost_next_service_must_be_catchable(session):
    change(session, THU, "x", first_late=30)
    # leaves 09:25: after the planned arrival (09:00) but before arrival + avg delay + 5 (09:35)
    train(session, "n1", THU, [(C, None, "09:25", 0), (B, "10:25", None, 0)], "RE3")
    train(session, "n2", THU, [(C, None, "09:40", 0), (B, "10:40", None, 2)], "RE4")
    options = search(session, A, B, limit=10)
    opt = next(o for o in options if o.legs[1].line == "RE2")
    assert opt.expected_arrival_delay_minutes == 22.0  # 09:40 train: 20 min later + 2 delay


def test_duration_across_dst_change_uses_elapsed_time():
    day = datetime(2026, 3, 29, tzinfo=BERLIN)  # clocks jump 02:00 -> 03:00
    run = Run("t", "RE1", A, B, at(day, "01:30"), at(day, "03:30"), 0)
    [service] = build_services([run])
    assert service.duration == 60


def test_berlin_handles_aware_and_naive():
    from datetime import UTC
    assert _berlin(datetime(2026, 11, 12, 9, 0, tzinfo=UTC)).hour == 10
    assert _berlin(datetime(2026, 11, 12, 9, 0)).hour == 9


def test_malformed_and_same_order_stop_ids_ignored(session):
    for sid, eva, kw in (("nodash", A, {}), ("x-abc", A, {})):
        upsert_stops(session, eva, "x", [Stop(stop_id=sid, departure=ev(THU, "08:10"))])
    # same order number at two stations is not a leg; neither are two stops at one station
    upsert_stops(session, A, "x", [Stop(stop_id="s-1", departure=ev(THU, "08:10"))])
    upsert_stops(session, B, "x", [Stop(stop_id="s-1", arrival=ev(THU, "09:10"))])
    upsert_stops(session, A, "x", [Stop(stop_id="r-1", departure=ev(THU, "08:10")),
                                   Stop(stop_id="r-2", arrival=ev(THU, "09:10"))])
    for row in session.scalars(select(StopEvent)):
        row.updated_at = NOW
    session.commit()
    assert load_runs(session, START, END, NOW) == []


def test_arrival_not_after_departure_is_no_run(session):
    train(session, "w", THU, [(A, None, "09:10", 0), (B, "08:10", None, 0)])
    assert load_runs(session, START, END, NOW) == []
