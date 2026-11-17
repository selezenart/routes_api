import pytest
from sqlalchemy import select

from tracker.collector.merge import merge
from tracker.collector.parser import parse_timetable
from tracker.db.models import StopEvent
from tracker.db.session import create_schema, make_engine, make_session_factory
from tracker.db.store import upsert_stops


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_schema(engine)
    with make_session_factory(engine)() as session:
        yield session


def test_upsert_stores_one_row_per_stop(session, plan_xml, fchg_xml):
    stops = merge(parse_timetable(plan_xml).stops, parse_timetable(fchg_xml).stops)

    count = upsert_stops(session, "8000157", "Heilbronn Hbf", stops)
    session.commit()

    rows = session.scalars(select(StopEvent).order_by(StopEvent.stop_id)).all()
    assert count == len(stops) == len(rows) == 5
    re8 = rows[0]
    assert (re8.eva, re8.station, re8.line) == ("8000157", "Heilbronn Hbf", "RE8")
    assert re8.planned_departure.hour == 12 and re8.planned_departure.minute == 6
    assert re8.changed_departure.minute == 14
    assert (re8.planned_platform, re8.changed_platform) == ("3", "5")
    assert re8.departure_delay == 8 and re8.arrival_delay == 7
    assert not re8.cancelled


def test_upsert_updates_existing_row_instead_of_duplicating(session, plan_xml, fchg_xml):
    plan = parse_timetable(plan_xml).stops
    upsert_stops(session, "8000157", "Heilbronn Hbf", plan)
    session.commit()

    upsert_stops(session, "8000157", "Heilbronn Hbf", merge(plan, parse_timetable(fchg_xml).stops))
    session.commit()

    rows = session.scalars(select(StopEvent)).all()
    assert len(rows) == 5
    rb18 = next(r for r in rows if r.number == "19510")
    assert rb18.cancelled


def test_upsert_fills_stats_columns(session, plan_xml, fchg_xml):
    stops = merge(parse_timetable(plan_xml).stops, parse_timetable(fchg_xml).stops)
    upsert_stops(session, "8000157", "Heilbronn Hbf", stops)
    session.commit()

    re8 = session.scalars(select(StopEvent).where(StopEvent.line == "RE8")).first()
    assert re8.planned_time == re8.planned_departure
    assert re8.delay_minutes == 8
    assert re8.hour_berlin == re8.planned_departure.hour
    assert re8.weekday_berlin == re8.planned_departure.weekday()
