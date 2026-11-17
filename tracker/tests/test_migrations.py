"""Alembic migrations match the SQLAlchemy model (SQLite, no network, no .env)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from tracker.db.models import Base

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_cfg(tmp_path: Path) -> tuple[Config, str]:
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "tracker" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, url


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_head_creates_stop_events(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    assert "stop_events" in _tables(url)


def test_migration_matches_model(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(ctx, Base.metadata) == []
    finally:
        engine.dispose()


def test_unique_constraint_and_indexes_exist(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        uniques = {u["name"] for u in insp.get_unique_constraints("stop_events")}
        indexes = {i["name"] for i in insp.get_indexes("stop_events")}
    finally:
        engine.dispose()
    assert "uq_stop_events_eva_stop_id" in uniques
    assert {"ix_stop_events_eva", "ix_stop_events_line"} <= indexes


def test_downgrade_base_removes_table_and_upgrade_again(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert "stop_events" not in _tables(url)
    command.upgrade(cfg, "head")
    assert "stop_events" in _tables(url)


def test_offline_mode_emits_sql(alembic_cfg, capsys):
    cfg, _ = alembic_cfg
    command.upgrade(cfg, "head", sql=True)
    assert "CREATE TABLE stop_events" in capsys.readouterr().out


def test_url_falls_back_to_settings(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'env.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "tracker" / "db" / "migrations"))
    command.upgrade(cfg, "head")
    assert "stop_events" in _tables(url)


def _insert_old_row(conn, stop_id, **cols):
    base = {"eva": "8000157", "stop_id": stop_id, "station": "Heilbronn Hbf", "cancelled": 0,
            "updated_at": "2026-11-13 12:00:00"}
    base.update(cols)
    names = ", ".join(base)
    marks = ", ".join(f":{k}" for k in base)
    conn.execute(text(f"INSERT INTO stop_events ({names}) VALUES ({marks})"), base)


def test_0002_backfills_rows_written_at_0001(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "0001")
    engine = create_engine(url)
    with engine.begin() as conn:
        # SQLite keeps Berlin wall time: 23:30 on Friday 13 Nov 2026, 8 minutes late.
        _insert_old_row(conn, "dep", planned_departure="2026-11-13 23:30:00",
                        changed_departure="2026-11-13 23:38:00",
                        planned_arrival="2026-11-13 23:20:00")
        _insert_old_row(conn, "arr", planned_arrival="2026-11-14 00:05:00",
                        changed_arrival="2026-11-14 00:07:00")
        _insert_old_row(conn, "none")
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        rows = {
            r.stop_id: r
            for r in conn.execute(text(
                "SELECT stop_id, planned_time, delay_minutes, hour_berlin, weekday_berlin FROM stop_events"
            ))
        }
    engine.dispose()
    assert (rows["dep"].delay_minutes, rows["dep"].hour_berlin, rows["dep"].weekday_berlin) == (8, 23, 4)
    assert rows["dep"].planned_time.startswith("2026-11-13 23:30")
    assert (rows["arr"].delay_minutes, rows["arr"].hour_berlin, rows["arr"].weekday_berlin) == (2, 0, 5)
    assert rows["none"].planned_time is None and rows["none"].delay_minutes is None


def test_0002_indexes_and_columns(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("stop_events")}
        columns = {c["name"] for c in insp.get_columns("stop_events")}
    finally:
        engine.dispose()
    assert indexes["ix_stop_events_eva_planned_time"] == ["eva", "planned_time"]
    assert indexes["ix_stop_events_line_planned_time"] == ["line", "planned_time"]
    assert {"planned_time", "delay_minutes", "hour_berlin", "weekday_berlin"} <= columns


def test_downgrade_to_0001_drops_stats_columns(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        columns = {c["name"] for c in insp.get_columns("stop_events")}
        indexes = {i["name"] for i in insp.get_indexes("stop_events")}
    finally:
        engine.dispose()
    assert not columns & {"planned_time", "delay_minutes", "hour_berlin", "weekday_berlin"}
    assert indexes == {"ix_stop_events_eva", "ix_stop_events_line"}
