import gzip
from datetime import datetime, timezone

from tracker.collector.archive import archive_response
from tracker.collector.parser import BERLIN

WHEN = datetime(2026, 11, 13, 12, 10, 5, tzinfo=BERLIN)


def test_writes_gzip_in_berlin_date_folder(tmp_path):
    path = archive_response(tmp_path, "8000157", "fchg", WHEN, "<timetable>ä</timetable>")

    assert path == tmp_path / "2026-11-13" / "8000157" / "fchg_121005.xml.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert handle.read() == "<timetable>ä</timetable>"


def test_uses_berlin_time_not_input_zone(tmp_path):
    late_utc = datetime(2026, 11, 13, 23, 30, 0, tzinfo=timezone.utc)  # already 00:30 on the 14th in Berlin

    path = archive_response(tmp_path, "1", "plan_26111400", late_utc, "x")

    assert path == tmp_path / "2026-11-14" / "1" / "plan_26111400_003000.xml.gz"


def test_never_overwrites(tmp_path):
    first = archive_response(tmp_path, "1", "fchg", WHEN, "one")
    second = archive_response(tmp_path, "1", "fchg", WHEN, "two")
    third = archive_response(tmp_path, "1", "fchg", WHEN, "three")

    assert [p.name for p in (first, second, third)] == [
        "fchg_121005.xml.gz",
        "fchg_121005_1.xml.gz",
        "fchg_121005_2.xml.gz",
    ]
    assert gzip.decompress(first.read_bytes()) == b"one"
    assert gzip.decompress(third.read_bytes()) == b"three"
