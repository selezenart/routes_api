"""Most reliable connection between two collected stations. Week 4, task A.

Pipeline: load observed past stop events in the period, link them into leg runs by trip id
(same trip, earlier stop order at A than at B), group runs into services (line, A, B, planned
departure time of day, day type), then search the station graph for direct and one-transfer
connections (DFS over stations, as in the original route finder in src/routes/utils.py).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal

from sqlalchemy.orm import Session

from tracker.api.schemas import ConnectionOption

MIN_TRANSFER_MINUTES = 5
WINDOW_HOURS = 3
MISSED_TRANSFER_PENALTY_MINUTES = 60  # when no later train to wait for is known


def search_connections(
    session: Session,
    from_eva: str,
    to_eva: str,
    depart_after: time,
    day_type: Literal["weekday", "weekend"],
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    max_transfers: int = 1,
    limit: int = 3,
) -> list[ConnectionOption]:
    """Up to ``limit`` options leaving ``from_eva`` within WINDOW_HOURS after ``depart_after``.

    Ranked by expected arrival (planned arrival + expected delay), ties by higher on_time_share.
    Only stops observed at or after their planned time count (as in tracker/db/stats.py).
    """
    raise NotImplementedError  # week 4, task A
