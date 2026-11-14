"""Retry API calls that fail for temporary reasons."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from tracker.collector.client import TimetablesError

T = TypeVar("T")

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def call_with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` and return its result, retrying temporary failures.

    Temporary: ``TimetablesError`` with a status in ``RETRY_STATUS``, or ``httpx.TransportError``
    (timeouts, connection errors). Waits ``base_delay * 2**n`` seconds before retry n+1,
    capped at ``max_delay``. After ``attempts`` tries the last error is raised. Any other
    error (e.g. 401/403) is raised at once without retrying.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except (TimetablesError, httpx.TransportError) as error:
            if isinstance(error, TimetablesError) and error.status_code not in RETRY_STATUS:
                raise
            if attempt == attempts - 1:
                raise
            sleep(min(base_delay * 2**attempt, max_delay))
    raise ValueError("attempts must be at least 1")
