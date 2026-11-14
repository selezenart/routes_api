from datetime import datetime

import httpx
import pytest

from tracker.collector.client import BASE_URL, TimetablesClient, TimetablesError
from tracker.collector.parser import BERLIN


def make_client(handler):
    return TimetablesClient("my-id", "my-key", transport=httpx.MockTransport(handler))


def test_sends_auth_headers_and_builds_plan_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, text="<timetable/>")

    with make_client(handler) as client:
        client.plan("8000157", datetime(2026, 11, 13, 9, 30, tzinfo=BERLIN))

    assert seen["url"] == f"{BASE_URL}/plan/8000157/261113/09"
    assert seen["headers"]["DB-Client-Id"] == "my-id"
    assert seen["headers"]["DB-Api-Key"] == "my-key"
    assert seen["headers"]["accept"] == "application/xml"


def test_plan_converts_time_to_berlin_hour():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, text="<timetable/>")

    utc_time = datetime.fromisoformat("2026-11-13T23:30:00+00:00")  # 00:30 next day in Berlin
    with make_client(handler) as client:
        client.plan("8000157", utc_time)

    assert seen["path"].endswith("/plan/8000157/261114/00")


@pytest.mark.parametrize(
    ("method", "path"),
    [("full_changes", "/fchg/8000157"), ("recent_changes", "/rchg/8000157")],
)
def test_change_endpoints(method, path):
    def handler(request):
        assert str(request.url) == BASE_URL + path
        return httpx.Response(200, text="<timetable/>")

    with make_client(handler) as client:
        assert getattr(client, method)("8000157") == "<timetable/>"


def test_station_search_escapes_pattern():
    def handler(request):
        assert request.url.raw_path.endswith(b"/station/Heilbronn%20Hbf")
        return httpx.Response(200, text="<stations/>")

    with make_client(handler) as client:
        client.find_stations("Heilbronn Hbf")


def test_plan_hour_without_data_returns_empty_timetable():
    with make_client(lambda request: httpx.Response(404)) as client:
        assert client.plan("8000157", datetime(2026, 11, 13, 3, tzinfo=BERLIN)) == "<timetable/>"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_errors_raise_without_leaking_the_key(status):
    with make_client(lambda request: httpx.Response(status, text="nope")) as client:
        with pytest.raises(TimetablesError) as err:
            client.full_changes("8000157")

    assert err.value.status_code == status
    assert "my-key" not in str(err.value)
