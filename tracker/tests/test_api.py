"""API tests: fake stats functions and a fake session, no database."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tracker.api import routes
from tracker.api.main import create_app
from tracker.api.schemas import ConnectionLeg, ConnectionOption, HourStats, LineStats, StationStats

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 17, 12, 30, tzinfo=BERLIN)
EVA = "8000096"  # Stuttgart Hbf, in STATIONS


def _station(eva=EVA, name="Stuttgart Hbf", stops=10):
    return StationStats(eva=eva, name=name, stops=stops, cancelled=1, on_time_share=0.8, avg_delay_minutes=3.5)


def _line(line="RE8", stops=4):
    return LineStats(line=line, stops=stops, cancelled=0, on_time_share=0.5, avg_delay_minutes=7.0)


def _hour(hour=8):
    return HourStats(hour=hour, stops=3, cancelled=0, on_time_share=1.0, avg_delay_minutes=1.0)


class Fakes:
    """Records calls and returns canned rows; set the attributes to change the answers."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.stations = [_station()]
        self.lines = [_line()]
        self.hours = [_hour()]

    def station_stats(self, session, start, end, now, **kw):
        self.calls.append(("station_stats", {"start": start, "end": end, "now": now, **kw}))
        return self.stations

    def line_stats(self, session, start, end, now, **kw):
        self.calls.append(("line_stats", {"start": start, "end": end, "now": now, **kw}))
        return self.lines

    def hour_stats(self, session, start, end, now, **kw):
        self.calls.append(("hour_stats", {"start": start, "end": end, "now": now, **kw}))
        return self.hours


class FakeSession:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    monkeypatch.setattr(routes, "station_stats", f.station_stats)
    monkeypatch.setattr(routes, "line_stats", f.line_stats)
    monkeypatch.setattr(routes, "hour_stats", f.hour_stats)
    return f


@pytest.fixture
def sessions():
    return []


@pytest.fixture
def client(fakes, sessions):
    def factory():
        s = FakeSession()
        sessions.append(s)
        return s

    return TestClient(create_app(factory, clock=lambda: NOW))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_session_closed_after_request(client, sessions):
    client.get("/stations")
    assert len(sessions) == 1 and sessions[0].closed


def test_stations_default_period(client, fakes):
    r = client.get("/stations")
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == {"start": "2026-11-11", "end": "2026-11-17"}
    assert body["stations"][0]["eva"] == EVA
    (name, kw), = fakes.calls
    assert name == "station_stats"
    assert kw["start"] == datetime(2026, 11, 11, tzinfo=BERLIN)
    assert kw["end"] == datetime(2026, 11, 18, tzinfo=BERLIN)
    assert kw["now"] == NOW
    assert kw["start"].tzinfo is not None


def test_explicit_period(client, fakes):
    r = client.get("/stations", params={"from": "2026-03-28", "to": "2026-03-30"})
    assert r.status_code == 200
    assert r.json()["period"] == {"start": "2026-03-28", "end": "2026-03-30"}
    kw = fakes.calls[0][1]
    assert kw["start"] == datetime(2026, 3, 28, tzinfo=BERLIN)
    assert kw["end"] == datetime(2026, 3, 31, tzinfo=BERLIN)  # exclusive, next midnight Berlin
    assert kw["start"].utcoffset().total_seconds() == 3600
    assert kw["end"].utcoffset().total_seconds() == 7200  # DST switch on 2026-03-29


def test_only_from_ends_today(client):
    r = client.get("/stations", params={"from": "2026-11-10"})
    assert r.json()["period"] == {"start": "2026-11-10", "end": "2026-11-17"}


def test_only_to_covers_seven_days(client):
    r = client.get("/stations", params={"to": "2026-11-10"})
    assert r.json()["period"] == {"start": "2026-11-04", "end": "2026-11-10"}


def test_today_uses_berlin_date(fakes, sessions):
    late_utc = datetime(2026, 11, 17, 23, 30, tzinfo=ZoneInfo("UTC"))  # already 18th in Berlin
    c = TestClient(create_app(FakeSession, clock=lambda: late_utc))
    assert c.get("/stations").json()["period"]["end"] == "2026-11-18"


def test_422_from_after_to(client):
    r = client.get("/stations", params={"from": "2026-11-10", "to": "2026-11-09"})
    assert r.status_code == 422
    assert "from" in str(r.json()["detail"])


def test_422_span_over_92_days(client):
    r = client.get("/stations", params={"from": "2026-08-01", "to": "2026-11-02"})  # 94 days
    assert r.status_code == 422
    assert "92" in str(r.json()["detail"])


def test_span_of_exactly_92_days_ok(client):
    r = client.get("/stations", params={"from": "2026-08-17", "to": "2026-11-16"})  # 92 days
    assert r.status_code == 200


def test_422_future_date(client):
    r = client.get("/stations", params={"to": "2026-11-18"})
    assert r.status_code == 422
    assert "future" in str(r.json()["detail"])
    assert client.get("/stations", params={"from": "2026-11-18"}).status_code == 422


def test_422_bad_date_format(client):
    assert client.get("/stations", params={"from": "yesterday"}).status_code == 422


def test_station_detail(client, fakes):
    fakes.lines = [_line("ICE 512")]
    r = client.get(f"/stations/{EVA}")
    assert r.status_code == 200
    body = r.json()
    assert body["station"]["name"] == "Stuttgart Hbf"
    assert body["by_hour"][0]["hour"] == 8
    assert body["worst_lines"][0]["line"] == "ICE 512"
    by_name = {n: kw for n, kw in fakes.calls}
    assert by_name["station_stats"]["eva"] == EVA
    assert by_name["hour_stats"]["eva"] == EVA
    assert by_name["line_stats"]["eva"] == EVA
    assert by_name["line_stats"]["limit"] == 5


def test_station_detail_unknown_eva_404(client, fakes):
    r = client.get("/stations/1234567")
    assert r.status_code == 404
    assert fakes.calls == []


def test_station_detail_without_stops_returns_zeros(client, fakes):
    fakes.stations = []
    fakes.lines = []
    fakes.hours = []
    r = client.get(f"/stations/{EVA}")
    assert r.status_code == 200
    body = r.json()
    assert body["station"] == {
        "eva": EVA, "name": "Stuttgart Hbf", "stops": 0, "cancelled": 0,
        "on_time_share": None, "avg_delay_minutes": None,
    }
    assert body["by_hour"] == [] and body["worst_lines"] == []


def test_lines(client, fakes):
    r = client.get("/lines", params={"from": "2026-11-01", "to": "2026-11-02"})
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == {"start": "2026-11-01", "end": "2026-11-02"}
    assert body["lines"][0]["line"] == "RE8"
    assert fakes.calls[0][0] == "line_stats"


def test_line_detail_with_url_encoded_space(client, fakes):
    fakes.lines = [_line("ICE 512", stops=6)]
    r = client.get("/lines/ICE%20512")
    assert r.status_code == 200
    body = r.json()
    assert body["line"] == "ICE 512"
    assert body["summary"]["stops"] == 6
    assert "line" not in body["summary"]
    assert body["by_station"][0]["eva"] == EVA
    assert body["by_hour"][0]["hour"] == 8
    by_name = {n: kw for n, kw in fakes.calls}
    assert by_name["line_stats"]["line"] == "ICE 512"
    assert by_name["station_stats"]["line"] == "ICE 512"
    assert by_name["hour_stats"]["line"] == "ICE 512"


def test_line_detail_no_stops_404(client, fakes):
    fakes.lines = []
    r = client.get("/lines/XYZ")
    assert r.status_code == 404
    assert "XYZ" in r.json()["detail"]


def test_line_detail_422_applies(client):
    assert client.get("/lines/RE8", params={"from": "2026-11-10", "to": "2026-11-01"}).status_code == 422


def test_cors_allowed_origin(client):
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_other_origin_not_allowed(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_preflight_get_only(client):
    h = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    assert client.options("/health", headers=h).status_code == 400
    h["Access-Control-Request-Method"] = "GET"
    assert client.options("/health", headers=h).status_code == 200


def test_docs_and_openapi(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Bahn Delay Tracker API"
    assert {"/health", "/stations", "/stations/{eva}", "/lines", "/lines/{line}", "/connections"} <= set(spec["paths"])
    for path in spec["paths"].values():
        assert path["get"]["summary"] and path["get"]["tags"]
    tags = {route: spec["paths"][route]["get"]["tags"] for route in spec["paths"]}
    assert tags["/health"] == ["health"]  # listed once in /docs, not also under "stats"
    assert tags["/connections"] == ["connections"]
    assert all(t == ["stats"] for route, t in tags.items() if route not in ("/health", "/connections"))


# --- /connections: fake search_connections ---

FRA = "8000105"


def _option():
    leg = ConnectionLeg(
        line="ICE 512", from_eva=EVA, from_name="Stuttgart Hbf", to_eva=FRA, to_name="Frankfurt(Main)Hbf",
        departure="08:00", arrival="09:30", runs=12, avg_arrival_delay_minutes=4.0,
        on_time_share=0.75, cancelled_share=0.0,
    )
    return ConnectionOption(
        legs=[leg], transfers=0, transfer_minutes=[], planned_departure="08:00", planned_arrival="09:30",
        planned_duration_minutes=90, missed_transfer_share=None, expected_arrival_delay_minutes=4.0,
        on_time_share=0.75,
    )


@pytest.fixture
def search(monkeypatch):
    calls = []
    result = {"options": [_option()]}

    def fake(session, from_eva, to_eva, depart_after, day_type, start, end, now, **kw):
        calls.append({
            "session": session, "from_eva": from_eva, "to_eva": to_eva, "depart_after": depart_after,
            "day_type": day_type, "start": start, "end": end, "now": now, **kw,
        })
        return result["options"]

    monkeypatch.setattr(routes, "search_connections", fake)
    fake.calls = calls
    fake.result = result
    return fake


def _conn(client, **params):
    base = {"from_eva": EVA, "to_eva": FRA, "depart_after": "08:00"}
    return client.get("/connections", params={**base, **params})


def test_connections_params_passed_through(client, search):
    from datetime import time

    r = _conn(client, depart_after="07:45", day="weekend", **{"from": "2026-11-01", "to": "2026-11-05"})
    assert r.status_code == 200
    (c,) = search.calls
    assert (c["from_eva"], c["to_eva"]) == (EVA, FRA)
    assert c["depart_after"] == time(7, 45)
    assert c["day_type"] == "weekend"
    assert c["start"] == datetime(2026, 11, 1, tzinfo=BERLIN)
    assert c["end"] == datetime(2026, 11, 6, tzinfo=BERLIN)
    assert c["now"] == NOW
    assert isinstance(c["session"], FakeSession)
    body = r.json()
    assert body["from_name"] == "Stuttgart Hbf" and body["to_name"] == "Frankfurt(Main)Hbf"
    assert body["depart_after"] == "07:45" and body["day_type"] == "weekend"
    assert body["period"] == {"start": "2026-11-01", "end": "2026-11-05"}
    assert body["options"][0]["legs"][0]["line"] == "ICE 512"
    assert body["message"] is None


def test_connections_default_day_type_and_period(client, search):
    r = _conn(client)  # NOW is Tuesday 2026-11-17
    assert r.status_code == 200
    assert r.json()["day_type"] == "weekday"
    assert r.json()["period"] == {"start": "2026-10-21", "end": "2026-11-17"}  # 28 days
    c = search.calls[0]
    assert c["start"] == datetime(2026, 10, 21, tzinfo=BERLIN)
    assert c["end"] == datetime(2026, 11, 18, tzinfo=BERLIN)


def test_connections_default_day_type_weekend_in_berlin(search):
    sat_utc = datetime(2026, 11, 21, 23, 30, tzinfo=ZoneInfo("UTC"))  # Sunday 22nd in Berlin
    c = TestClient(create_app(FakeSession, clock=lambda: sat_utc))
    assert _conn(c).json()["day_type"] == "weekend"


def test_connections_only_from_or_to_default(client, search):
    assert _conn(client, to="2026-11-10").json()["period"] == {"start": "2026-10-14", "end": "2026-11-10"}
    assert _conn(client, **{"from": "2026-11-10"}).json()["period"] == {"start": "2026-11-10", "end": "2026-11-17"}


@pytest.mark.parametrize("params", [
    {"from": "2026-11-10", "to": "2026-11-09"},
    {"to": "2026-11-18"},
    {"from": "2026-08-01", "to": "2026-11-02"},
])
def test_connections_period_422(client, search, params):
    assert _conn(client, **params).status_code == 422
    assert search.calls == []


def test_connections_unknown_station_404(client, search):
    assert _conn(client, from_eva="1234567").status_code == 404
    assert _conn(client, to_eva="1234567").status_code == 404
    assert search.calls == []


def test_connections_same_station_422(client, search):
    assert _conn(client, to_eva=EVA).status_code == 422
    assert search.calls == []


@pytest.mark.parametrize("bad", ["8", "25:00", "08:60", "8:00", "0800", "ab:cd", "", "08:00\n", "0\u0668:00"])
def test_connections_bad_time_422(client, search, bad):
    assert _conn(client, depart_after=bad).status_code == 422
    assert search.calls == []


def test_connections_bad_day_422(client, search):
    assert _conn(client, day="holiday").status_code == 422


def test_connections_missing_params_422(client, search):
    assert client.get("/connections").status_code == 422
    assert client.get("/connections", params={"from_eva": EVA, "to_eva": FRA}).status_code == 422


def test_connections_empty_options_message(client, search):
    search.result["options"] = []
    body = _conn(client, depart_after="08:15", day="weekday").json()
    assert body["options"] == []
    assert body["message"] == (
        "No connection between Stuttgart Hbf and Frankfurt(Main)Hbf departing 08:15-11:15 "
        "on weekdays in the observed data."
    )
    assert "weekends" in _conn(client, day="weekend").json()["message"]


def test_connections_session_closed(client, search, sessions):
    _conn(client)
    assert len(sessions) == 1 and sessions[0].closed


def test_connections_cors_still_get_only(client, search):
    h = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    assert client.options("/connections", headers=h).status_code == 400
    h["Access-Control-Request-Method"] = "GET"
    assert client.options("/connections", headers=h).status_code == 200


def test_responses_do_not_leak_settings(client, monkeypatch):
    monkeypatch.setenv("DB_API_KEY", "super-secret-key")
    text = client.get("/stations").text + client.get("/openapi.json").text
    assert "super-secret-key" not in text


def test_get_default_clock_is_berlin_aware():
    from tracker.api.main import default_clock

    assert default_clock().utcoffset() is not None


def test_import_main_touches_no_database():
    code = (
        "import sqlalchemy, sys\n"
        "def boom(*a, **k): raise SystemExit('connected')\n"
        "sqlalchemy.create_engine = boom\n"
        "import tracker.api.main as m\n"
        "assert m.app is not None\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={"PATH": "", "DATABASE_URL": "postgresql+psycopg://x:y@nowhere.invalid/db"},
    )
    assert r.returncode == 0, r.stderr


def test_lazy_app_session_factory_builds_engine_on_first_use(monkeypatch):
    from tracker.api import main

    made = []

    class FakeSettings:
        database_url = "sqlite://"

    monkeypatch.setattr(main, "load_settings", lambda require_api=True: FakeSettings())
    monkeypatch.setattr(main, "_lazy_factory", None)
    real = main.make_engine

    def spy(url):
        made.append(url)
        return real(url)

    monkeypatch.setattr(main, "make_engine", spy)
    s1 = main.lazy_session()
    s1.close()
    s2 = main.lazy_session()
    s2.close()
    assert made == ["sqlite://"]



# --- end to end: real SQLite and the real stats functions, no fakes ---

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)
OTHER_EVA = "8000105"


def _stop(sid, line, late=0, at=T0):
    from tracker.collector.parser import Event, Stop

    dep = Event(planned_time=at, changed_time=at + timedelta(minutes=late) if late else None, line=line)
    return Stop(stop_id=sid, category="X", number=sid, departure=dep)


@pytest.fixture
def real_client(tmp_path):
    from sqlalchemy import update

    from tracker.db.models import StopEvent
    from tracker.db.session import create_schema, make_engine, make_session_factory
    from tracker.db.store import upsert_stops

    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        # Stuttgart: seven lines (L0 late 0 .. L5 late 5, plus RE8 late 12 twice); Frankfurt: noise.
        stuttgart = [_stop(f"s{i}", f"L{i}", late=i) for i in range(6)]
        stuttgart += [_stop("s6", "RE8", late=10), _stop("s7", "RE8", late=14)]
        upsert_stops(s, EVA, "Stuttgart Hbf (stored)", stuttgart)
        upsert_stops(s, OTHER_EVA, "Frankfurt(Main)Hbf", [_stop("f1", "RE8", late=40), _stop("f2", "ICE 512", late=30)])
        s.execute(update(StopEvent).values(updated_at=NOW))  # observed after planned time
        s.commit()
    yield TestClient(create_app(factory, clock=lambda: NOW))
    engine.dispose()


def test_e2e_station_detail_filters_by_eva_and_limits_lines(real_client):
    body = real_client.get(f"/stations/{EVA}").json()
    assert body["station"]["name"] == "Stuttgart Hbf (stored)"
    assert body["station"]["stops"] == 8  # Frankfurt stops do not leak in
    assert body["by_hour"] == [{**body["by_hour"][0], "hour": 10, "stops": 8}]
    lines = body["worst_lines"]
    assert len(lines) == 5
    assert lines[0]["line"] == "RE8" and lines[0]["stops"] == 2  # not 3: Frankfurt's RE8 excluded
    assert lines[0]["avg_delay_minutes"] == 12.0


def test_e2e_station_list_names_and_order(real_client):
    stations = real_client.get("/stations").json()["stations"]
    assert [s["eva"] for s in stations] == [OTHER_EVA, EVA]
    assert stations[1]["name"] == "Stuttgart Hbf (stored)"


def test_e2e_line_detail_summary_matches_line(real_client):
    body = real_client.get("/lines/RE8").json()
    assert body["summary"]["stops"] == 3
    assert body["summary"]["avg_delay_minutes"] == pytest.approx((10 + 14 + 40) / 3, abs=0.1)
    assert sum(s["stops"] for s in body["by_station"]) == 3
    assert {s["eva"] for s in body["by_station"]} == {EVA, OTHER_EVA}
    assert body["by_hour"][0]["stops"] == 3
    assert real_client.get("/lines/ICE%20512").json()["summary"]["stops"] == 1
    assert real_client.get("/lines/NOPE").status_code == 404


@pytest.fixture
def real_search_client(tmp_path):
    """Real SQLite DB and the real search_connections; the DB is empty, tests seed it."""
    from tracker.db.session import create_schema, make_engine, make_session_factory

    engine = make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    yield TestClient(create_app(factory, clock=lambda: NOW)), factory
    engine.dispose()


def test_e2e_connections_empty_history(real_search_client):
    client, _ = real_search_client
    r = client.get(
        "/connections", params={"from_eva": EVA, "to_eva": FRA, "depart_after": "08:00", "day": "weekday"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["options"] == []
    assert body["from_name"] == "Stuttgart Hbf"
    assert "No connection between Stuttgart Hbf and Frankfurt(Main)Hbf" in body["message"]
    assert body["period"] == {"start": "2026-10-21", "end": "2026-11-17"}


def test_e2e_connections_seeded_direct_train(real_search_client):
    from sqlalchemy import update

    from tracker.collector.parser import Event, Stop
    from tracker.db.models import StopEvent
    from tracker.db.store import upsert_stops

    client, factory = real_search_client
    # Mon-Wed 2026-11-09..11, before the pinned clock: ICE 512 08:10 -> 09:40, arriving 0, 4, 8 min late.
    with factory() as s:
        for day, late in ((9, 0), (10, 4), (11, 8)):
            dep = datetime(2026, 11, day, 8, 10, tzinfo=BERLIN)
            arr = datetime(2026, 11, day, 9, 40, tzinfo=BERLIN)
            trip = f"trip{day}"
            upsert_stops(s, EVA, "Stuttgart Hbf", [Stop(
                stop_id=f"{trip}-1", category="ICE", number="512",
                departure=Event(planned_time=dep, line="ICE 512"),
            )])
            upsert_stops(s, FRA, "Frankfurt(Main)Hbf", [Stop(
                stop_id=f"{trip}-2", category="ICE", number="512",
                arrival=Event(planned_time=arr, changed_time=arr + timedelta(minutes=late) if late else None,
                              line="ICE 512"),
            )])
        s.execute(update(StopEvent).values(updated_at=NOW))  # observed after planned time
        s.commit()

    r = client.get("/connections", params={"from_eva": EVA, "to_eva": FRA, "depart_after": "08:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["day_type"] == "weekday" and body["message"] is None
    opt = body["options"][0]
    assert len(body["options"]) == 1
    assert opt["transfers"] == 0 and opt["transfer_minutes"] == []
    assert (opt["planned_departure"], opt["planned_arrival"], opt["planned_duration_minutes"]) == ("08:10", "09:40", 90)
    (leg,) = opt["legs"]
    assert (leg["line"], leg["from_eva"], leg["to_eva"]) == ("ICE 512", EVA, FRA)
    assert (leg["from_name"], leg["to_name"]) == ("Stuttgart Hbf", "Frankfurt(Main)Hbf")
    assert (leg["departure"], leg["arrival"], leg["runs"]) == ("08:10", "09:40", 3)
    assert leg["avg_arrival_delay_minutes"] == 4.0
    assert leg["on_time_share"] == pytest.approx(2 / 3, abs=0.001)  # 8 min late is not on time
    assert leg["cancelled_share"] == 0.0
    assert opt["on_time_share"] == pytest.approx(2 / 3, abs=0.001)
    # Weekend search sees nothing of this weekday history.
    r2 = client.get("/connections", params={"from_eva": EVA, "to_eva": FRA, "depart_after": "08:00", "day": "weekend"})
    assert r2.json()["options"] == []
