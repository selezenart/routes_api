"""Alembic migrations match the SQLAlchemy model (SQLite, no network, no .env)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

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
