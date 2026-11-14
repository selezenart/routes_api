"""HTTP client for the DB Timetables API (developers.deutschebahn.com).

Returns raw XML text so callers can both parse it and archive it unchanged.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx

from tracker.collector.parser import BERLIN

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
EMPTY_TIMETABLE = "<timetable/>"


class TimetablesError(Exception):
    """The API answered with an error status. Never includes credentials."""

    def __init__(self, status_code: int, path: str):
        super().__init__(f"Timetables API returned HTTP {status_code} for {path}")
        self.status_code = status_code
        self.path = path


class TimetablesClient:
    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "DB-Client-Id": client_id,
                "DB-Api-Key": api_key,
                "accept": "application/xml",
            },
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> TimetablesClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def find_stations(self, pattern: str) -> str:
        """Stations whose name matches ``pattern``, with their EVA numbers."""
        return self._get(f"/station/{quote(pattern, safe='')}")

    def plan(self, eva: str, when: datetime) -> str:
        """Planned stops at ``eva`` during the Berlin-time hour containing ``when``."""
        local = when.astimezone(BERLIN)
        return self._get(f"/plan/{eva}/{local:%y%m%d}/{local:%H}", empty_on_404=True)

    def full_changes(self, eva: str) -> str:
        """All currently known changes at ``eva``."""
        return self._get(f"/fchg/{eva}")

    def recent_changes(self, eva: str) -> str:
        """Changes at ``eva`` learned in roughly the last two minutes."""
        return self._get(f"/rchg/{eva}")

    def _get(self, path: str, *, empty_on_404: bool = False) -> str:
        response = self._http.get(path)
        if response.status_code == 404 and empty_on_404:
            return EMPTY_TIMETABLE  # the API answers 404 for hours with no trains
        if response.status_code != 200:
            raise TimetablesError(response.status_code, path)
        return response.text
