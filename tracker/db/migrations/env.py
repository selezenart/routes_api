"""Alembic environment: offline and online migrations for the tracker schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from tracker.config import load_settings
from tracker.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL set on the Config (tests) wins; otherwise the app settings."""
    return config.get_main_option("sqlalchemy.url") or load_settings(require_api=False).database_url


def _options(url: str) -> dict:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "render_as_batch": url.startswith("sqlite"),
    }


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_options(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, **_options(url))
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
