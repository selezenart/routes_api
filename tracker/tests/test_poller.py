import gzip
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from tracker.collector.client import TimetablesClient
from tracker.collector.parser import BERLIN
from tracker.collector.poller import Poller
from tracker.db.models import StopEvent
from tracker.db.session import create_schema, make_engine, make_session_factory

NOW = datetime(2026, 11, 13, 12, 10, tzinfo=BERLIN)
EMPTY = "<timetable/>"


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class Api:
    """MockTransport handler that records requests and serves fixtures."""

    def __init__(self, plan_xml, fchg_xml):
        self.plan_xml, self.fchg_xml = plan_xml, fchg_xml
        self.paths: list[str] = []
        self.failing: set[str] = set()  # EVA numbers whose fchg answers 500

    def __call__(self, request):
        path = request.url.path
        self.paths.append(path)
        if "/plan/" in path:
            eva = path.split("/")[-3]
            return httpx.Response(200, text=self.plan_xml if eva == "8000157" and path.endswith("/12") else EMPTY)
        eva = path.rsplit("/", 1)[-1]
        if eva in self.failing:
            return httpx.Response(500)
        return httpx.Response(200, text=self.fchg_xml)

    def plan_hours(self, eva="8000157"):
        return [p.rsplit("/", 1)[-1] for p in self.paths if f"/plan/{eva}/" in p]


def make_poller(plan_xml, fchg_xml, *, stations=None, archive_dir=None, clock=None, **kwargs):
    api = Api(plan_xml, fchg_xml)
    client = TimetablesClient("id", "key", transport=httpx.MockTransport(api))
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    factory = make_session_factory(engine)
    delays: list[float] = []
    poller = Poller(
        client,
        factory,
        stations=stations or {"8000157": "Heilbronn Hbf"},
        archive_dir=archive_dir,
        clock=clock or Clock(),
        sleep=delays.append,
        **kwargs,
    )
    return poller, api, factory, delays


def rows(factory):
    with factory() as session:
        return list(session.scalars(select(StopEvent).order_by(StopEvent.eva, StopEvent.stop_id)))


def test_refresh_fetches_whole_window_once(plan_xml, fchg_xml):
    poller, api, _, _ = make_poller(plan_xml, fchg_xml)

    results = poller.refresh_plans()
    assert [r.error for r in results] == [None]
    assert api.plan_hours() == ["10", "11", "12", "13", "14"]

    poller.refresh_plans()
    assert len(api.plan_hours()) == 5  # nothing new to fetch


def test_window_slides_and_drops_old_hours(plan_xml, fchg_xml):
    clock = Clock()
    poller, api, _, _ = make_poller(plan_xml, fchg_xml, clock=clock)
    poller.refresh_plans()

    clock.now = NOW + timedelta(hours=1)  # 13:10 -> window 11..15
    poller.refresh_plans()

    assert api.plan_hours()[5:] == ["15"]
    assert sorted(h.astimezone(BERLIN).hour for h in poller._plans["8000157"]) == [11, 12, 13, 14, 15]

    clock.now = NOW + timedelta(hours=3)  # 15:10 -> the 12:xx plan has left the window
    poller.refresh_plans()
    assert 12 not in {h.astimezone(BERLIN).hour for h in poller._plans["8000157"]}


def test_poll_merges_plan_and_changes_and_stores(plan_xml, fchg_xml):
    poller, _, factory, _ = make_poller(plan_xml, fchg_xml)
    poller.refresh_plans()

    results = poller.poll_changes()

    assert [(r.eva, r.stops_saved, r.error) for r in results] == [("8000157", 5, None)]
    stored = rows(factory)
    assert len(stored) == 5  # 4 planned + 1 extra train; stop at 14:10 has no plan and is dropped
    assert {r.station for r in stored} == {"Heilbronn Hbf"}
    re8 = next(r for r in stored if r.number == "19412")
    assert re8.departure_delay == 8 and re8.changed_platform == "5"
    assert next(r for r in stored if r.number == "19510").cancelled


def test_stops_outside_window_are_not_stored(plan_xml, fchg_xml):
    clock = Clock(NOW + timedelta(hours=5))  # 17:10, plan hour 12 is far outside
    poller, _, factory, _ = make_poller(plan_xml, fchg_xml, clock=clock)

    poller.poll_changes()  # no plans cached, window 15..19: extra train at 12:40 is outside

    assert rows(factory) == []


def test_poll_is_idempotent(plan_xml, fchg_xml):
    poller, _, factory, _ = make_poller(plan_xml, fchg_xml)
    poller.refresh_plans()
    poller.poll_changes()
    poller.poll_changes()

    assert len(rows(factory)) == 5


def test_failing_station_does_not_stop_others(plan_xml, fchg_xml, caplog):
    stations = {"8000157": "Heilbronn Hbf", "8000096": "Stuttgart Hbf"}
    poller, api, factory, delays = make_poller(plan_xml, fchg_xml, stations=stations)
    api.failing.add("8000157")
    poller.refresh_plans()

    with caplog.at_level(logging.INFO, logger="tracker.collector"):
        results = {r.eva: r for r in poller.poll_changes()}

    assert "500" in results["8000157"].error and results["8000157"].stops_saved == 0
    assert results["8000096"].error is None
    assert {r.eva for r in rows(factory)} == {"8000096"}
    assert delays == [2.0, 4.0, 8.0]  # 500 was retried before giving up
    assert any(r.levelno == logging.WARNING and "8000157" in r.message for r in caplog.records)
    assert any(r.levelno == logging.INFO and "8000096" in r.message for r in caplog.records)
    assert "DB-Api-Key" not in caplog.text


def test_failing_plan_fetch_is_reported_and_retried_next_time(plan_xml, fchg_xml):
    poller, api, _, _ = make_poller(plan_xml, fchg_xml)
    failing = {"on": True}

    def handler(request):
        if failing["on"] and "/plan/" in request.url.path:
            return httpx.Response(503)
        return api(request)

    poller._client._http._transport = httpx.MockTransport(handler)
    results = poller.refresh_plans()
    assert results[0].error and "503" in results[0].error
    assert poller._plans["8000157"] == {}

    failing["on"] = False
    assert poller.refresh_plans()[0].error is None
    assert len(poller._plans["8000157"]) == 5


def test_archives_raw_xml(tmp_path, plan_xml, fchg_xml):
    poller, _, _, _ = make_poller(plan_xml, fchg_xml, archive_dir=tmp_path)

    poller.refresh_plans()
    poller.poll_changes()

    folder = tmp_path / "2026-11-13" / "8000157"
    names = sorted(p.name for p in folder.iterdir())
    assert "fchg_121000.xml.gz" in names
    assert "plan_26111312_121000.xml.gz" in names
    assert len([n for n in names if n.startswith("plan_")]) == 5
    assert gzip.decompress((folder / "fchg_121000.xml.gz").read_bytes()).decode() == fchg_xml


def test_no_archive_without_dir(tmp_path, monkeypatch, plan_xml, fchg_xml):
    monkeypatch.chdir(tmp_path)
    poller, _, _, _ = make_poller(plan_xml, fchg_xml)
    poller.refresh_plans()
    poller.poll_changes()

    assert list(tmp_path.iterdir()) == []


def test_garbage_plan_xml_fails_only_that_station(plan_xml, fchg_xml):
    stations = {"8000096": "Stuttgart Hbf", "8000157": "Heilbronn Hbf"}
    poller, api, _, _ = make_poller(plan_xml, fchg_xml, stations=stations)
    good = api.__call__

    def handler(request):
        if "/plan/8000096/" in request.url.path:
            return httpx.Response(200, text="<timetable><broken")
        return good(request)

    poller._client._http._transport = httpx.MockTransport(handler)
    results = {r.eva: r for r in poller.refresh_plans()}

    assert results["8000096"].error
    assert results["8000157"].error is None
    assert len(poller._plans["8000157"]) == 5


def test_unwritable_archive_does_not_lose_data(tmp_path, plan_xml, fchg_xml, caplog):
    blocker = tmp_path / "archive"
    blocker.write_text("a file, not a folder")
    poller, _, factory, _ = make_poller(plan_xml, fchg_xml, archive_dir=blocker)

    with caplog.at_level(logging.WARNING, logger="tracker.collector"):
        plan_results = poller.refresh_plans()
        results = poller.poll_changes()

    assert plan_results[0].error is None
    assert results[0].error is None and results[0].stops_saved == 5
    assert len(rows(factory)) == 5
    assert any("archiving" in r.message for r in caplog.records)


def test_database_failure_isolated_to_one_station(plan_xml, fchg_xml):
    stations = {"8000157": "Heilbronn Hbf", "8000096": "Stuttgart Hbf"}
    poller, _, factory, _ = make_poller(plan_xml, fchg_xml, stations=stations)
    real = poller._session_factory
    calls = []

    def flaky_factory():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is down")
        return real()

    poller._session_factory = flaky_factory
    results = {r.eva: r for r in poller.poll_changes()}

    assert results["8000157"].error == "database is down"
    assert results["8000096"].error is None and results["8000096"].stops_saved == 1
    assert {r.eva for r in rows(factory)} == {"8000096"}


def test_poll_fetches_missing_newest_hour_without_refresh(plan_xml, fchg_xml):
    clock = Clock()
    poller, api, _, _ = make_poller(plan_xml, fchg_xml, clock=clock)
    poller.refresh_plans()
    before = len(api.plan_hours())

    clock.now = NOW + timedelta(hours=1)  # 13:10, hour 15 not cached yet
    poller.poll_changes()

    assert api.plan_hours()[before:] == ["15"]
    poller.poll_changes()
    assert len(api.plan_hours()) == before + 1  # fetched once only
