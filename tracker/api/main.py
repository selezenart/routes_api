"""FastAPI app factory. ``uvicorn tracker.api.main:app``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import BERLIN
from tracker.api.routes import router
from tracker.config import load_settings
from tracker.db.session import make_engine, make_session_factory

ALLOWED_ORIGINS = ["http://localhost:5173"]

_lazy_factory: sessionmaker[Session] | None = None


def default_clock() -> datetime:
    return datetime.now(BERLIN)


def lazy_session() -> Session:
    """Session from an engine built on first use, so importing this module never connects."""
    global _lazy_factory
    if _lazy_factory is None:
        _lazy_factory = make_session_factory(make_engine(load_settings(require_api=False).database_url))
    return _lazy_factory()


def create_app(
    session_factory: Callable[[], Session], clock: Callable[[], datetime] = default_clock
) -> FastAPI:
    app = FastAPI(title="Bahn Delay Tracker API", description="Delay statistics from Deutsche Bahn Timetables data.")
    app.state.session_factory = session_factory
    app.state.clock = clock
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET"])
    app.include_router(router)
    return app


app = create_app(lazy_session)
