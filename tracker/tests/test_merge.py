from tracker.collector.merge import merge
from tracker.collector.parser import parse_timetable


def merged(plan_xml, fchg_xml):
    stops = merge(parse_timetable(plan_xml).stops, parse_timetable(fchg_xml).stops)
    return {s.stop_id: s for s in stops}


def test_change_adds_actual_time_and_platform_to_planned_stop(plan_xml, fchg_xml):
    re8 = merged(plan_xml, fchg_xml)["1111111111111111111-2611131204-5"]

    assert (re8.category, re8.number) == ("RE", "19412")
    assert re8.departure.planned_platform == "3"
    assert re8.departure.changed_platform == "5"
    assert re8.arrival.delay_minutes == 7
    assert re8.departure.delay_minutes == 8


def test_cancellation_is_carried_over(plan_xml, fchg_xml):
    rb18 = merged(plan_xml, fchg_xml)["2222222222222222222-2611131215-1"]

    assert rb18.departure.cancelled
    assert rb18.departure.planned_time is not None


def test_stop_without_changes_counts_as_on_time(plan_xml, fchg_xml):
    ic = merged(plan_xml, fchg_xml)["3333333333333333333-2611131230-7"]

    assert ic.departure.delay_minutes == 0
    assert not ic.departure.cancelled


def test_extra_train_from_changes_is_kept(plan_xml, fchg_xml):
    extra = merged(plan_xml, fchg_xml)["6666666666666666666-2611131240-2"]

    assert extra.line_name == "RE8"
    assert extra.departure.delay_minutes == 2


def test_change_without_planned_data_is_dropped(plan_xml, fchg_xml):
    assert "5555555555555555555-2611131410-3" not in merged(plan_xml, fchg_xml)


def test_result_is_sorted_by_planned_time(plan_xml, fchg_xml):
    stops = merge(parse_timetable(plan_xml).stops, parse_timetable(fchg_xml).stops)

    times = [s.planned_time for s in stops]
    assert times == sorted(times)


def test_later_change_can_revoke_cancellation(plan_xml):
    plan = parse_timetable(plan_xml).stops
    cancelled = parse_timetable(
        '<timetable><s id="2222222222222222222-2611131215-1"><dp cs="c"/></s></timetable>'
    ).stops
    revoked = parse_timetable(
        '<timetable><s id="2222222222222222222-2611131215-1"><dp cs="p"/></s></timetable>'
    ).stops

    once = merge(plan, cancelled)
    twice = merge(once, revoked)

    rb18 = {s.stop_id: s for s in twice}["2222222222222222222-2611131215-1"]
    assert not rb18.departure.cancelled
