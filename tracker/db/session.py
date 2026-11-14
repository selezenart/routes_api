from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tracker.db.models import Base


def make_engine(url: str) -> Engine:
    """Engine for ``url`` with the tables created. Alembic migrations replace this in week 2."""
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
