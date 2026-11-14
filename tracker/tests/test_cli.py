import io
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func, select

from tracker import cli
from tracker.collector.client import TimetablesClient
from tracker.collector.parser import BERLIN
from tracker.collector.poller import Poller
from tracker.db.models import StopEvent
from tracker.db.session import create_schema, make_engine, make_session_factory

NOW = datetime(2026, 11, 13, 12, 10, tzinfo=BERLIN)


def fake_client(plan_xml, fchg_xml):
    def handler(request):
        path = request.url.path
        if "/plan/" in path:
            return httpx.Response(200, text=plan_xml if path.endswith("/12") else "<timetable/>")
        if "/fchg/" in path:
            return httpx.Response(200, text=fchg_xml)
        if "/station/" in path:
            return httpx.Response(
                200, text='<stations><station name="Heilbronn Hbf" eva="8000157"/></stations>'
            )
        return httpx.Response(404)

    return TimetablesClient("id", "key", transport=httpx.MockTransport(handler))


def run(argv, plan_xml, fchg_xml, **kwargs):
    out = io.StringIO()
    code = cli.main(argv, client=fake_client(plan_xml, fchg_xml), now=NOW, out=out, **kwargs)
    return code, out.getvalue()


def test_delays_prints_table_and_summary(plan_xml, fchg_xml):
    code, output = run(["delays", "--eva", "8000157"], plan_xml, fchg_xml)

    assert code == 0
    assert "Heilbronn Hbf (8000157)" in output
    assert "12:06  RE 19412" in output and "+8" in output
    assert "cancelled" in output
    assert "5 stops, 1 late (6+ min), 1 cancelled" in output


def test_delays_save_writes_to_database(plan_xml, fchg_xml):
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)

    code, output = run(
        ["delays", "--save"], plan_xml, fchg_xml, session_factory=make_session_factory(engine)
    )

    assert code == 0
    assert "Saved 5 stop events" in output
    with make_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(StopEvent)) == 5


def test_stations_prints_eva_numbers(plan_xml, fchg_xml):
    code, output = run(["stations", "Heilbronn"], plan_xml, fchg_xml)

    assert code == 0
    assert "8000157  Heilbronn Hbf" in output


def test_record_writes_raw_responses(tmp_path, plan_xml, fchg_xml):
    code, _ = run(["record", "--out", str(tmp_path), "--hours", "1"], plan_xml, fchg_xml)

    assert code == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["fchg_8000157_2611131210.xml", "plan_8000157_26111312.xml"]
    assert (tmp_path / "plan_8000157_26111312.xml").read_text(encoding="utf-8") == plan_xml


def test_missing_credentials_give_clear_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DB_CLIENT_ID", raising=False)
    monkeypatch.delenv("DB_API_KEY", raising=False)
    err = io.StringIO()

    code = cli.main(["delays"], err=err)

    assert code == 2
    assert "DB_CLIENT_ID" in err.getvalue()


def collect_client(plan_xml, fchg_xml, failing=()):
    def handler(request):
        path = request.url.path
        if "/plan/" in path:
            return httpx.Response(200, text=plan_xml if "/8000157/" in path and path.endswith("/12") else "<timetable/>")
        if path.rsplit("/", 1)[-1] in failing:
            return httpx.Response(500)
        return httpx.Response(200, text=fchg_xml)

    return TimetablesClient("id", "key", transport=httpx.MockTransport(handler))


def run_collect(argv, client, factory, tmp_path):
    out = io.StringIO()
    code = cli.main(
        argv,
        client=client,
        session_factory=factory,
        now=NOW,
        out=out,
        archive_dir=tmp_path,
        sleep=lambda _: None,
    )
    return code, out.getvalue()


def test_collect_once_stores_and_archives(tmp_path, plan_xml, fchg_xml):
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    factory = make_session_factory(engine)

    code, output = run_collect(
        ["collect", "--once", "--stations", "8000157"], collect_client(plan_xml, fchg_xml), factory, tmp_path
    )

    assert code == 0
    assert "8000157  Heilbronn Hbf:" in output and "stops saved" in output
    assert output.count("\n") == 1  # one line, one station
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(StopEvent)) > 0
    assert any(tmp_path.rglob("fchg_*.xml.gz"))


def test_collect_once_exit_code_is_1_only_if_all_stations_fail(tmp_path, plan_xml, fchg_xml):
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    factory = make_session_factory(engine)
    both = ["collect", "--once", "--stations", "8000157", "8000096"]

    code, output = run_collect(both, collect_client(plan_xml, fchg_xml, failing={"8000157"}), factory, tmp_path)
    assert code == 0
    assert "8000157  Heilbronn Hbf: error" in output and "8000096  Stuttgart Hbf: 1 stops saved" in output

    code, _ = run_collect(
        both, collect_client(plan_xml, fchg_xml, failing={"8000157", "8000096"}), factory, tmp_path
    )
    assert code == 1


def test_build_scheduler_has_both_jobs_with_safe_options():
    scheduler = cli.build_scheduler(Poller(None, None, stations={}))

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert jobs["refresh_plans"].trigger.interval == timedelta(minutes=60)
    assert jobs["poll_changes"].trigger.interval == timedelta(minutes=3)
    for job in jobs.values():
        assert job.max_instances == 1 and job.coalesce is True
    assert not scheduler.running


def test_sigterm_handler_shuts_scheduler_down(monkeypatch):
    import signal

    installed = {}
    monkeypatch.setattr(signal, "signal", lambda signum, handler: installed.update({signum: handler}))
    calls = []

    class FakeScheduler:
        def shutdown(self, wait=True):
            calls.append(wait)

    cli._stop_on_sigterm(FakeScheduler())
    installed[signal.SIGTERM](signal.SIGTERM, None)

    assert calls == [False]


def test_collect_survives_unexpected_error_in_first_cycle(tmp_path, plan_xml, fchg_xml):
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)

    def broken_plans(request):
        if "/plan/" in request.url.path:
            return httpx.Response(200, text="<timetable><broken")
        return httpx.Response(200, text=fchg_xml)

    client = TimetablesClient("id", "key", transport=httpx.MockTransport(broken_plans))
    code, output = run_collect(
        ["collect", "--once", "--stations", "8000157"], client, make_session_factory(engine), tmp_path
    )

    assert code == 0
    assert "plan error" in output
