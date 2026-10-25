"""Wires services together. Kept separate from FastAPI so tests can build custom containers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory
from app.services.calibration_jobs import CalibrationService
from app.services.data_store import MarketDataStore
from app.services.decision_analysis import DecisionService
from app.services.elexon_client import ElexonClient


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    client: ElexonClient
    store: MarketDataStore
    calibrations: CalibrationService
    decisions: DecisionService

    def close(self) -> None:
        self.calibrations.shutdown()
        self.client.close()
        self.engine.dispose()


def build_container(
    settings: Settings,
    *,
    client: ElexonClient | None = None,
    run_inline: bool = False,
) -> Container:
    engine = make_engine(settings.database_url)
    init_db(engine)
    sf = make_session_factory(engine)
    client = client or ElexonClient(
        settings.elexon_base_url,
        timeout=settings.elexon_timeout_seconds,
        max_retries=settings.elexon_max_retries,
        backoff_base=settings.elexon_backoff_base_seconds,
        backoff_max=settings.elexon_backoff_max_seconds,
    )
    store = MarketDataStore(sf, client)
    calibrations = CalibrationService(sf, store, settings, run_inline=run_inline)
    calibrations.recover_interrupted()
    decisions = DecisionService(sf, store, settings)
    return Container(settings, engine, sf, client, store, calibrations, decisions)
