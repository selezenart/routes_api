"""create stop_events

Revision ID: 0001
Revises:
Create Date: 2026-11-14 18:55:42.047284
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("stop_events",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("eva", sa.String(length=16), nullable=False),
    sa.Column("stop_id", sa.String(length=64), nullable=False),
    sa.Column("station", sa.String(length=128), nullable=False),
    sa.Column("category", sa.String(length=16), nullable=True),
    sa.Column("number", sa.String(length=16), nullable=True),
    sa.Column("line", sa.String(length=32), nullable=True),
    sa.Column("planned_arrival", sa.DateTime(timezone=True), nullable=True),
    sa.Column("changed_arrival", sa.DateTime(timezone=True), nullable=True),
    sa.Column("planned_departure", sa.DateTime(timezone=True), nullable=True),
    sa.Column("changed_departure", sa.DateTime(timezone=True), nullable=True),
    sa.Column("planned_platform", sa.String(length=8), nullable=True),
    sa.Column("changed_platform", sa.String(length=8), nullable=True),
    sa.Column("cancelled", sa.Boolean(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("eva", "stop_id", name="uq_stop_events_eva_stop_id")
    )
    op.create_index("ix_stop_events_eva", "stop_events", ["eva"])
    op.create_index("ix_stop_events_line", "stop_events", ["line"])


def downgrade() -> None:
    op.drop_index("ix_stop_events_line", table_name="stop_events")
    op.drop_index("ix_stop_events_eva", table_name="stop_events")
    op.drop_table("stop_events")
