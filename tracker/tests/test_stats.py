"""Stats SQL on in-memory SQLite, rows built by upsert_stops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tracker.collector.parser import BERLIN, Event, Stop
from tracker.db.models import StopEvent
from tracker.db.session import create_schema, make_engine, make_session_factory
from tracker.db.stats import hour_stats, line_stats, station_stats
from tracker.db.store import upsert_stops

START = datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN)
END = datetime(2026, 11, 17, 0, 0, tzinfo=BERLIN)
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=BERLIN)
T = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)


def stop(sid, line="RE8", *, at=T, late=0, cancelled=False):
    dep = Event(
        planned_time=at,
        changed_time=at + timedelta(minutes=late) if late else None,
        line=line,
        status="c" if cancelled else None,
    )
    return Stop(stop_id=sid, category="RE", number=sid, departure=dep)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    with make_session_factory(engine)() as session:
        yield session


def put(session, eva, name, *stops, observed_at=NOW):
    """Store stops as if the collector last polled them at ``observed_at`` (Berlin)."""
    upsert_stops(session, eva, name, stops)
    for row in session.scalars(select(StopEvent).where(StopEvent.eva == eva)):
        row.updated_at = observed_at
    session.commit()


def test_on_time_edge_five_vs_six_minutes(session):
    put(session, "1", "A", stop("a", late=5), stop("b", late=6))
    [s] = station_stats(session, START, END, NOW)
    assert (s.eva, s.name, s.stops, s.cancelled) == ("1", "A", 2, 0)
    assert s.on_time_share == 0.5
    assert s.avg_delay_minutes == 5.5


def test_cancelled_counted_but_not_in_share_or_average(session):
    put(session, "1", "A", stop("a", late=2), stop("b", late=40, cancelled=True))
    [s] = station_stats(session, START, END, NOW)
    assert (s.stops, s.cancelled) == (2, 1)
    assert s.on_time_share == 1.0
    assert s.avg_delay_minutes == 2.0


def test_only_cancelled_gives_none(session):
    put(session, "1", "A", stop("a", cancelled=True))
    [s] = station_stats(session, START, END, NOW)
    assert (s.stops, s.cancelled, s.on_time_share, s.avg_delay_minutes) == (1, 1, None, None)


def test_future_stops_excluded(session):
    now = T + timedelta(hours=1)
    put(session, "1", "A", stop("a"), stop("b", at=now + timedelta(minutes=1)),
        stop("c", at=now))
    [s] = station_stats(session, START, END, now)
    assert s.stops == 1


def test_period_start_inclusive_end_exclusive(session):
    put(session, "1", "A", stop("in", at=START), stop("end", at=END),
        stop("before", at=START - timedelta(minutes=1)),
        stop("last", at=END - timedelta(minutes=1)))
    [s] = station_stats(session, START, END, NOW)
    assert s.stops == 2


def test_bounds_in_other_timezone_are_converted(session):
    put(session, "1", "A", stop("in", at=START))
    utc = timezone.utc
    [s] = station_stats(session, START.astimezone(utc), END.astimezone(utc), NOW.astimezone(utc))
    assert s.stops == 1


def test_eva_and_line_filters(session):
    put(session, "1", "A", stop("a", "RE8"), stop("b", "S4"))
    put(session, "2", "B", stop("c", "RE8"))
    assert [s.eva for s in station_stats(session, START, END, NOW, eva="2")] == ["2"]
    [s] = station_stats(session, START, END, NOW, line="S4")
    assert (s.eva, s.stops) == ("1", 1)
    assert [x.line for x in line_stats(session, START, END, NOW, eva="1", line="RE8")] == ["RE8"]
    assert sum(h.stops for h in hour_stats(session, START, END, NOW, eva="1")) == 2
    assert sum(h.stops for h in hour_stats(session, START, END, NOW, line="RE8")) == 2


def test_sort_worst_first_nulls_last_then_name(session):
    put(session, "1", "Zed", stop("a", late=3))
    put(session, "2", "Alpha", stop("b", late=3))
    put(session, "3", "Bad", stop("c", late=20))
    put(session, "4", "Cancelled", stop("d", cancelled=True))
    names = [s.name for s in station_stats(session, START, END, NOW)]
    assert names == ["Bad", "Alpha", "Zed", "Cancelled"]


def test_line_stats_sort_and_limit(session):
    put(session, "1", "A", stop("a", "S4", late=1), stop("b", "RE8", late=9),
        stop("c", "ICE 512", late=3))
    lines = line_stats(session, START, END, NOW)
    assert [x.line for x in lines] == ["RE8", "ICE 512", "S4"]
    assert [x.line for x in line_stats(session, START, END, NOW, limit=2)] == ["RE8", "ICE 512"]


def test_hour_bucketing_in_berlin_time(session):
    late_evening = datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc)  # 23:30 Berlin
    put(session, "1", "A", stop("a", at=late_evening), stop("b", at=T), stop("c", at=T, late=7))
    hours = hour_stats(session, START, END, NOW)
    assert [h.hour for h in hours] == [10, 23]
    assert hours[0].stops == 2 and hours[0].on_time_share == 0.5
    assert hours[1].stops == 1


def test_empty_result(session):
    assert station_stats(session, START, END, NOW) == []
    assert line_stats(session, START, END, NOW) == []
    assert hour_stats(session, START, END, NOW) == []


def test_unobserved_past_stop_excluded_everywhere(session):
    # last polled before the stop was due: its delay is only a prediction
    put(session, "1", "A", stop("old", late=0), observed_at=T - timedelta(minutes=1))
    assert station_stats(session, START, END, NOW) == []
    assert line_stats(session, START, END, NOW) == []
    assert hour_stats(session, START, END, NOW) == []


def test_observed_stop_included_unobserved_not(session):
    put(session, "1", "A", stop("seen", late=3))
    put(session, "1", "A", stop("unseen", at=T + timedelta(hours=2)), observed_at=T)
    [s] = station_stats(session, START, END, NOW)
    assert s.stops == 1
    put(session, "2", "B", stop("exact"), observed_at=T)  # updated_at == planned_time counts
    assert {x.eva for x in station_stats(session, START, END, NOW)} == {"1", "2"}


def test_renamed_station_gives_one_row(session):
    put(session, "1", "Old Name", stop("a", late=2))
    put(session, "1", "New Name", stop("b", late=4, at=T + timedelta(hours=1)))
    [s] = station_stats(session, START, END, NOW)
    assert (s.eva, s.stops, s.avg_delay_minutes) == ("1", 2, 3.0)
    assert s.name in {"Old Name", "New Name"}


def test_period_spanning_dst_change(session):
    start = datetime(2026, 3, 28, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 3, 30, 0, 0, tzinfo=BERLIN)
    now = datetime(2026, 4, 1, tzinfo=BERLIN)
    day = lambda d, h, m: datetime(2026, 3, d, h, m, tzinfo=BERLIN)  # noqa: E731
    put(session, "1", "A",
        stop("cet", at=day(29, 1, 30)), stop("cest", at=day(29, 3, 30)),
        stop("last", at=day(29, 23, 59)), stop("first", at=day(28, 0, 0)),
        stop("end", at=day(30, 0, 0)), stop("before", at=day(27, 23, 59)),
        observed_at=now)
    assert [(h.hour, h.stops) for h in hour_stats(session, start, end, now)] == [
        (0, 1), (1, 1), (3, 1), (23, 1)]
    assert station_stats(session, start, end, now)[0].stops == 4
