"""Command line for the delay tracker.

    python -m tracker.cli stations Heilbronn
    python -m tracker.cli delays --eva 8000157 [--hours 3] [--save]
    python -m tracker.cli record --eva 8000157
    python -m tracker.cli collect [--once] [--stations EVA ...]
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session, sessionmaker

from tracker.collector.client import TimetablesClient, TimetablesError
from tracker.collector.merge import merge
from tracker.collector.parser import BERLIN, Stop, parse_stations, parse_timetable
from tracker.collector.poller import CycleResult, Poller
from tracker.config import ConfigError, load_settings
from tracker.db.session import create_schema, make_engine, make_session_factory
from tracker.db.store import upsert_stops
from tracker.stations import STATIONS

HEILBRONN_HBF = "8000157"
PLAN_REFRESH_MINUTES = 60
CHANGES_POLL_MINUTES = 3
LATE_MINUTES = 6  # DB counts a train as on time below 6 minutes
RECORDED_DIR = Path(__file__).parent / "tests" / "fixtures" / "recorded"


def main(
    argv: list[str] | None = None,
    *,
    client: TimetablesClient | None = None,
    session_factory: sessionmaker[Session] | None = None,
    now: datetime | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    archive_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = _build_parser().parse_args(argv)
    fixed_now = now  # tests pin the clock; a real run follows the wall clock
    now = (now or datetime.now(BERLIN)).astimezone(BERLIN)

    try:
        if client is None:
            settings = load_settings()
            client = TimetablesClient(settings.client_id, settings.api_key)
        collecting = args.command == "collect"
        if collecting and archive_dir is None:
            archive_dir = Path(load_settings(require_api=False).raw_archive_dir)
        if (getattr(args, "save", False) or collecting) and session_factory is None:
            url = load_settings(require_api=False).database_url
            engine = make_engine(url)
            if url.startswith("sqlite"):  # PostgreSQL gets its tables from Alembic
                create_schema(engine)
            session_factory = make_session_factory(engine)
    except ConfigError as error:
        print(error, file=err)
        return 2

    with client:
        try:
            return args.handler(
                args,
                client=client,
                session_factory=session_factory,
                now=now,
                out=out,
                archive_dir=archive_dir,
                sleep=sleep,
                fixed_now=fixed_now,
            )
        except TimetablesError as error:
            print(f"Error: {error}", file=err)
            return 1


def _stations(args, *, client: TimetablesClient, out: TextIO, **_) -> int:
    stations = parse_stations(client.find_stations(args.pattern))
    if not stations:
        print(f"No station matches {args.pattern!r}.", file=out)
    for station in stations:
        print(f"{station.eva}  {station.name}", file=out)
    return 0


def _delays(args, *, client: TimetablesClient, session_factory, now: datetime, out: TextIO, **_) -> int:
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    end = start + timedelta(hours=args.hours)
    plans = [parse_timetable(client.plan(args.eva, start + timedelta(hours=i))) for i in range(args.hours)]
    changes = parse_timetable(client.full_changes(args.eva))

    planned = [stop for plan in plans for stop in plan.stops]
    stops = [s for s in merge(planned, changes.stops) if s.planned_time and start <= s.planned_time < end]
    station = next((t.station for t in [*plans, changes] if t.station), args.eva)

    print(f"{station} ({args.eva}) · {start:%d.%m.%Y %H:%M}–{end:%H:%M}", file=out)
    print(file=out)
    print(f"{'Time':<7}{'Train':<11}{'Line':<9}{'Platform':<10}{'Delay':>5}  Note", file=out)
    for stop in stops:
        print(_row(stop), file=out)
    print(file=out)
    print(_summary(stops), file=out)

    if args.save:
        with session_factory() as session:
            count = upsert_stops(session, args.eva, station, stops)
            session.commit()
        print(f"Saved {count} stop events to the database.", file=out)
    return 0


def _record(args, *, client: TimetablesClient, now: datetime, out: TextIO, **_) -> int:
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    hour = now.replace(minute=0, second=0, microsecond=0)
    files = {
        f"plan_{args.eva}_{when:%y%m%d%H}.xml": client.plan(args.eva, when)
        for when in (hour + timedelta(hours=i) for i in range(args.hours))
    }
    files[f"fchg_{args.eva}_{now:%y%m%d%H%M}.xml"] = client.full_changes(args.eva)
    for name, xml in files.items():
        (folder / name).write_text(xml, encoding="utf-8")
        print(f"Wrote {folder / name}", file=out)
    return 0


def _collect(
    args, *, client: TimetablesClient, session_factory, out: TextIO, archive_dir, sleep, fixed_now, **_
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    unknown = [eva for eva in args.stations or [] if eva not in STATIONS]
    stations = {eva: STATIONS.get(eva, eva) for eva in args.stations or STATIONS}
    clock = {"clock": lambda: fixed_now} if fixed_now else {}
    poller = Poller(client, session_factory, stations=stations, archive_dir=archive_dir, sleep=sleep, **clock)
    if unknown:
        logging.getLogger("tracker.collector").warning("Unknown EVA numbers, using them as names: %s", unknown)

    plan_results = poller.refresh_plans()
    results = poller.poll_changes()
    for result in results:
        print(_cycle_line(result, stations[result.eva], plan_results), file=out)
    if args.once:
        return 1 if all(r.error for r in results) else 0

    scheduler = build_scheduler(poller)
    print(
        f"Collecting {len(stations)} stations: plans every {PLAN_REFRESH_MINUTES} min, "
        f"changes every {CHANGES_POLL_MINUTES} min. Ctrl-C to stop.",
        file=out,
    )
    _stop_on_sigterm(scheduler)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


def _stop_on_sigterm(scheduler: BlockingScheduler) -> None:
    """Make ``docker stop`` (SIGTERM) end the scheduler cleanly, exit code 0."""

    def handler(signum, frame):
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, handler)


def _cycle_line(result: CycleResult, name: str, plan_results: list[CycleResult]) -> str:
    plan_error = next((p.error for p in plan_results if p.eva == result.eva and p.error), None)
    line = f"{result.eva}  {name}: " + (f"error: {result.error}" if result.error else f"{result.stops_saved} stops saved")
    return f"{line} (plan error: {plan_error})" if plan_error else line


def build_scheduler(poller: Poller) -> BlockingScheduler:
    """Scheduler with the two recurring jobs. The caller runs the first cycle and starts it."""
    scheduler = BlockingScheduler(timezone=BERLIN)
    options = {"max_instances": 1, "coalesce": True}
    scheduler.add_job(
        poller.refresh_plans, "interval", minutes=PLAN_REFRESH_MINUTES, id="refresh_plans", **options
    )
    scheduler.add_job(
        poller.poll_changes, "interval", minutes=CHANGES_POLL_MINUTES, id="poll_changes", **options
    )
    return scheduler


def _row(stop: Stop) -> str:
    main_event = stop.main_event
    platform = main_event.planned_platform or ""
    if main_event.changed_platform and main_event.changed_platform != platform:
        platform = f"{platform}→{main_event.changed_platform}"
    if stop.cancelled:
        delay, note = "–", "cancelled"
    else:
        minutes = stop.delay_minutes or 0
        delay = f"+{minutes}" if minutes > 0 else "0"
        note = "extra train" if main_event.status == "a" else ""
    time = f"{stop.planned_time:%H:%M}"
    return f"{time:<7}{stop.train_name:<11}{stop.line_name:<9}{platform:<10}{delay:>5}  {note}".rstrip()


def _summary(stops: list[Stop]) -> str:
    running = [s for s in stops if not s.cancelled and s.delay_minutes is not None]
    late = sum(1 for s in running if s.delay_minutes >= LATE_MINUTES)
    cancelled = sum(1 for s in stops if s.cancelled)
    average = sum(s.delay_minutes for s in running) / len(running) if running else 0.0
    return (
        f"{len(stops)} stops, {late} late ({LATE_MINUTES}+ min), {cancelled} cancelled, "
        f"average delay {average:.1f} min"
    )


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracker", description="Deutsche Bahn delay tracker")
    commands = parser.add_subparsers(dest="command", required=True)

    stations = commands.add_parser("stations", help="find a station's EVA number")
    stations.add_argument("pattern", help="station name, e.g. 'Heilbronn Hbf'")
    stations.set_defaults(handler=_stations)

    delays = commands.add_parser("delays", help="show current delays at a station")
    delays.add_argument("--eva", default=HEILBRONN_HBF, help="station EVA number (default: Heilbronn Hbf)")
    delays.add_argument("--hours", type=_positive_int, default=3, help="hours to show, starting 1 hour ago")
    delays.add_argument("--save", action="store_true", help="store the result in the database")
    delays.set_defaults(handler=_delays)

    record = commands.add_parser("record", help="save raw API responses as test fixtures")
    record.add_argument("--eva", default=HEILBRONN_HBF)
    record.add_argument("--hours", type=_positive_int, default=2, help="planned hours to save, from now")
    record.add_argument("--out", default=str(RECORDED_DIR))
    record.set_defaults(handler=_record)

    collect = commands.add_parser("collect", help="poll all stations on a schedule and store the stops")
    collect.add_argument("--once", action="store_true", help="run one cycle and exit")
    collect.add_argument("--stations", nargs="+", metavar="EVA", help="EVA numbers (default: all)")
    collect.set_defaults(handler=_collect)
    return parser


if __name__ == "__main__":
    sys.exit(main())
