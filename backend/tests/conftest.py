from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.main import create_app
from app.services.elexon_client import ElexonClient
from tests.fakes import FakeElexon


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def fake() -> FakeElexon:
    return FakeElexon()


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Set TEST_DATABASE_URL (e.g. postgresql+psycopg://user@localhost/windtest) to run the suite on
    # PostgreSQL. The schema is dropped and recreated for every test.
    pg_url = os.environ.get("TEST_DATABASE_URL")
    if pg_url:
        from sqlalchemy import create_engine

        from app.db.base import Base
        from app.db.session import init_db

        eng = create_engine(pg_url)
        init_db(eng)
        Base.metadata.drop_all(eng)
        eng.dispose()
    return Settings(
        database_url=pg_url or f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        elexon_base_url="https://elexon.test/bmrs/api/v1",
        elexon_max_retries=2,
        cors_origins="http://localhost:5173",
        log_level="WARNING",
        min_calibration_pairs=72,
        low_sample_pairs=500,
    )


def make_client(settings: Settings, handler) -> ElexonClient:
    return ElexonClient(
        settings.elexon_base_url,
        timeout=5,
        max_retries=settings.elexon_max_retries,
        backoff_base=0.01,
        backoff_max=0.05,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _d: 0.0,
    )


@pytest.fixture
def container(settings, fake) -> Iterator[Container]:
    c = build_container(settings, client=make_client(settings, fake), run_inline=True)
    yield c
    c.close()


@pytest.fixture
def api(settings, container) -> Iterator[TestClient]:
    app = create_app(settings, container)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
