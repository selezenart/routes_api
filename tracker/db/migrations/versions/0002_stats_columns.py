"""add precomputed stats columns and indexes, backfill existing rows

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17 10:00:00

Stop the collector before running this upgrade: the backfill reads rows in Python batches and
writes them back by id, so rows the collector writes meanwhile could be left without the new
columns (or be overwritten with stale values).
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BERLIN = ZoneInfo("Europe/Berlin")
BATCH = 1000


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive Berlin wall time; PostgreSQL returns aware datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BERLIN)
    return value.astimezone(BERLIN)


def _computed(row) -> dict:
    """Same rules as tracker.db.store: departure if there is one, else arrival."""
    if row.planned_departure is not None or row.changed_departure is not None:
        planned, changed = row.planned_departure, row.changed_departure
    else:
        planned, changed = row.planned_arrival, row.changed_arrival
    planned, changed = _aware(planned), _aware(changed)
    if planned is None:
        return {"planned_time": None, "delay_minutes": None, "hour_berlin": None, "weekday_berlin": None}
    delay = 0 if changed is None else int((changed - planned).total_seconds() // 60)
    return {
        "planned_time": planned,
        "delay_minutes": delay,
        "hour_berlin": planned.hour,
        "weekday_berlin": planned.weekday(),
    }


def upgrade() -> None:
    with op.batch_alter_table("stop_events") as batch:
        batch.add_column(sa.Column("planned_time", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("delay_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("hour_berlin", sa.SmallInteger(), nullable=True))
        batch.add_column(sa.Column("weekday_berlin", sa.SmallInteger(), nullable=True))
    op.create_index("ix_stop_events_eva_planned_time", "stop_events", ["eva", "planned_time"])
    op.create_index("ix_stop_events_line_planned_time", "stop_events", ["line", "planned_time"])
    _backfill()


def _backfill() -> None:
    if op.get_context().as_sql:  # offline SQL generation has no rows to read
        return
    conn = op.get_bind()
    table = sa.table(
        "stop_events",
        sa.column("id", sa.Integer),
        sa.column("planned_arrival", sa.DateTime(timezone=True)),
        sa.column("changed_arrival", sa.DateTime(timezone=True)),
        sa.column("planned_departure", sa.DateTime(timezone=True)),
        sa.column("changed_departure", sa.DateTime(timezone=True)),
        sa.column("planned_time", sa.DateTime(timezone=True)),
        sa.column("delay_minutes", sa.Integer),
        sa.column("hour_berlin", sa.SmallInteger),
        sa.column("weekday_berlin", sa.SmallInteger),
    )
    last_id = 0
    while True:
        rows = conn.execute(
            sa.select(
                table.c.id, table.c.planned_arrival, table.c.changed_arrival,
                table.c.planned_departure, table.c.changed_departure,
            )
            .where(table.c.id > last_id)
            .order_by(table.c.id)
            .limit(BATCH)
        ).fetchall()
        if not rows:
            return
        updates = [{"row_id": row.id, **_computed(row)} for row in rows]
        conn.execute(
            table.update().where(table.c.id == sa.bindparam("row_id")),
            updates,
        )
        last_id = rows[-1].id


def downgrade() -> None:
    op.drop_index("ix_stop_events_line_planned_time", table_name="stop_events")
    op.drop_index("ix_stop_events_eva_planned_time", table_name="stop_events")
    with op.batch_alter_table("stop_events") as batch:
        batch.drop_column("weekday_berlin")
        batch.drop_column("hour_berlin")
        batch.drop_column("delay_minutes")
        batch.drop_column("planned_time")
