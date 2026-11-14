from datetime import datetime
from pathlib import Path

import pytest

from tracker.collector.merge import merge
from tracker.collector.parser import BERLIN, parse_stations, parse_time, parse_timetable

RECORDED = sorted((Path(__file__).parent / "fixtures" / "recorded").glob("*.xml"))


def test_parse_time_reads_db_format_as_berlin_time():
    assert parse_time("2611131204") == datetime(2026, 11, 13, 12, 4, tzinfo=BERLIN)


@pytest.mark.parametrize("value", [None, ""])
def test_parse_time_returns_none_for_missing_value(value):
    assert parse_time(value) is None


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time("not-a-time")


def test_plan_reads_station_and_all_stops(plan_xml):
    timetable = parse_timetable(plan_xml)

    assert timetable.station == "Heilbronn Hbf"
    assert [s.stop_id for s in timetable.stops] == [
        "1111111111111111111-2611131204-5",
        "2222222222222222222-2611131215-1",
        "3333333333333333333-2611131230-7",
        "4444444444444444444-2611131250-9",
    ]


def test_plan_reads_train_arrival_and_departure(plan_xml):
    re8 = parse_timetable(plan_xml).stops[0]

    assert (re8.category, re8.number) == ("RE", "19412")
    assert re8.arrival.planned_time == datetime(2026, 11, 13, 12, 4, tzinfo=BERLIN)
    assert re8.arrival.planned_platform == "3"
    assert re8.departure.planned_time == datetime(2026, 11, 13, 12, 6, tzinfo=BERLIN)
    assert re8.departure.line == "RE8"
    assert re8.departure.changed_time is None
    assert not re8.departure.cancelled


def test_plan_handles_departure_only_and_arrival_only_stops(plan_xml):
    stops = parse_timetable(plan_xml).stops

    assert stops[1].arrival is None and stops[1].departure is not None
    assert stops[3].departure is None and stops[3].arrival is not None


def test_line_name_uses_line_number_or_falls_back_to_train_number(plan_xml):
    stops = parse_timetable(plan_xml).stops

    assert stops[0].line_name == "RE8"
    assert stops[2].line_name == "IC 2062"


def test_line_name_adds_category_to_a_bare_line_number():
    xml = '<timetable><s id="x"><tl c="S" n="37412"/><dp pt="2611131200" l="4"/></s></timetable>'

    assert parse_timetable(xml).stops[0].line_name == "S 4"


def test_message_only_change_has_no_arrival_or_departure(fchg_xml):
    stops = parse_timetable(fchg_xml).stops

    notice = next(s for s in stops if s.stop_id.startswith("3333"))
    assert notice.arrival is None and notice.departure is None


def test_changes_read_changed_time_platform_and_cancellation(fchg_xml):
    stops = {s.stop_id: s for s in parse_timetable(fchg_xml).stops}

    re8 = stops["1111111111111111111-2611131204-5"]
    assert re8.category is None  # changes usually omit the train label
    assert re8.arrival.changed_time == datetime(2026, 11, 13, 12, 11, tzinfo=BERLIN)
    assert re8.departure.changed_platform == "5"

    rb18 = stops["2222222222222222222-2611131215-1"]
    assert rb18.departure.cancelled
    assert rb18.departure.planned_time is None


def test_empty_timetable_has_no_stops():
    timetable = parse_timetable("<timetable/>")

    assert timetable.station is None
    assert timetable.stops == []


def test_parse_stations_reads_name_and_eva():
    xml = """<stations>
      <station name="Heilbronn Hbf" eva="8000157" ds100="TH" db="true"/>
      <station name="Heilbronn Pfühlpark" eva="8070793" ds100="TH  U" db="true"/>
    </stations>"""

    stations = parse_stations(xml)

    assert [(s.name, s.eva) for s in stations] == [
        ("Heilbronn Hbf", "8000157"),
        ("Heilbronn Pfühlpark", "8070793"),
    ]


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_recorded_responses_parse(path):
    timetable = parse_timetable(path.read_bytes())

    assert timetable.stops
    for stop in timetable.stops:
        assert stop.stop_id
        if path.name.startswith("plan_"):  # change feeds may hold message-only stops
            assert stop.planned_time is not None
            assert stop.category and stop.number


def test_recorded_plan_and_changes_merge():
    plans = [p for p in RECORDED if p.name.startswith("plan_")]
    changes = [p for p in RECORDED if p.name.startswith("fchg_")]
    if not (plans and changes):
        pytest.skip("no recorded responses yet: run `python -m tracker.cli record`")

    planned = [s for p in plans for s in parse_timetable(p.read_bytes()).stops]
    stops = merge(planned, parse_timetable(changes[0].read_bytes()).stops)

    assert len(stops) >= len(planned)
    for stop in stops:
        assert stop.planned_time is not None
        assert stop.line_name
        assert stop.delay_minutes is not None and stop.delay_minutes > -60
