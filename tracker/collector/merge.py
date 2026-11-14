"""Combine planned stops with the changes DB publishes for them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from tracker.collector.parser import BERLIN, Event, Stop

_LAST = datetime.max.replace(tzinfo=BERLIN)


def merge(planned: Iterable[Stop], changes: Iterable[Stop]) -> list[Stop]:
    """Apply ``changes`` to ``planned`` stops, matched by DB's stop id.

    A change for a stop we have no plan for is kept only if it brings its own
    planned time (an extra train); otherwise there is nothing to measure a delay
    against yet. The result is sorted by planned time.
    """
    by_id = {stop.stop_id: stop for stop in planned}
    for change in changes:
        base = by_id.get(change.stop_id)
        if base is not None:
            by_id[change.stop_id] = _merge_stop(base, change)
        elif change.planned_time is not None:
            by_id[change.stop_id] = change
    return sorted(by_id.values(), key=lambda stop: stop.planned_time or _LAST)


def _merge_stop(base: Stop, change: Stop) -> Stop:
    return replace(
        base,
        category=base.category or change.category,
        number=base.number or change.number,
        arrival=_merge_event(base.arrival, change.arrival),
        departure=_merge_event(base.departure, change.departure),
    )


def _merge_event(base: Event | None, change: Event | None) -> Event | None:
    if change is None:
        return base
    if base is None:
        return change if change.planned_time else None
    return Event(
        planned_time=base.planned_time or change.planned_time,
        changed_time=change.changed_time or base.changed_time,
        planned_platform=base.planned_platform or change.planned_platform,
        changed_platform=change.changed_platform or base.changed_platform,
        line=base.line or change.line,
        status=change.status or base.status,
    )
