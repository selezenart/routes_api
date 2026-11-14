from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tracker.db.models import Base


def make_engine(url: str) -> Engine:
    """Engine for ``url``. Tables come from Alembic (``alembic upgrade head``)."""
    return create_engine(url)


def create_schema(engine: Engine) -> None:
    """Create all tables directly. For tests and local SQLite only; PostgreSQL uses Alembic."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
