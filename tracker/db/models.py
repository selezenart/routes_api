from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StopEvent(Base):
    """One train stopping at one station, with planned and latest known times."""

    __tablename__ = "stop_events"
    __table_args__ = (
        UniqueConstraint("eva", "stop_id", name="uq_stop_events_eva_stop_id"),
        Index("ix_stop_events_eva_planned_time", "eva", "planned_time"),
        Index("ix_stop_events_line_planned_time", "line", "planned_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    eva: Mapped[str] = mapped_column(String(16), index=True)
    stop_id: Mapped[str] = mapped_column(String(64))
    station: Mapped[str] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(16))
    number: Mapped[str | None] = mapped_column(String(16))
    line: Mapped[str | None] = mapped_column(String(32), index=True)
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_platform: Mapped[str | None] = mapped_column(String(8))
    changed_platform: Mapped[str | None] = mapped_column(String(8))
    cancelled: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Precomputed for stats: main event (departure, else arrival) and its Berlin hour/weekday.
    planned_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delay_minutes: Mapped[int | None] = mapped_column(Integer)
    hour_berlin: Mapped[int | None] = mapped_column(SmallInteger)
    weekday_berlin: Mapped[int | None] = mapped_column(SmallInteger)  # 0 = Monday

    @property
    def arrival_delay(self) -> int | None:
        return _delay(self.planned_arrival, self.changed_arrival)

    @property
    def departure_delay(self) -> int | None:
        return _delay(self.planned_departure, self.changed_departure)


def _delay(planned: datetime | None, changed: datetime | None) -> int | None:
    if planned is None:
        return None
    if changed is None:
        return 0
    return int((changed - planned).total_seconds() // 60)
