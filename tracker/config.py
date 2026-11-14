"""Settings from environment variables, with a local ``.env`` file as a fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

DEFAULT_DATABASE_URL = "sqlite:///tracker.db"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    client_id: str
    api_key: str
    database_url: str

    def __repr__(self) -> str:  # keep secrets out of logs and tracebacks
        return f"Settings(client_id=***, api_key=***, database_url={self.database_url!r})"


def load_settings(*, require_api: bool = True) -> Settings:
    load_dotenv(find_dotenv(usecwd=True))
    client_id = os.environ.get("DB_CLIENT_ID", "")
    api_key = os.environ.get("DB_API_KEY", "")
    if require_api and not (client_id and api_key):
        raise ConfigError(
            "Missing DB_CLIENT_ID and/or DB_API_KEY. Copy .env.example to .env and fill "
            "them in, or set them as environment variables."
        )
    return Settings(
        client_id=client_id,
        api_key=api_key,
        database_url=os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
    )
