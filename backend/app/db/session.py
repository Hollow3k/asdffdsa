from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

logger = logging.getLogger(__name__)


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(url.database)), exist_ok=True)
        # Background calibration jobs use their own threads/sessions.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url, **kwargs)

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_db(engine: Engine) -> None:
    # Import models so they register on the metadata.
    from app.models import calibration, market_data  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
