from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import calibrations, coverage, decisions, health
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.core.errors import AppError

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=False
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        logger.info("Started; database=%s", app.state.container.engine.url.render_as_string(hide_password=True))
        yield
        app.state.container.close()

    app = FastAPI(
        title="Wind Procurement Decision Support",
        version="1.0.0",
        description=(
            "Decision support for day-ahead electricity procurement using Elexon national wind "
            "forecasts (WINDFOR) and outturn (FUELHH). error = forecast - actual; positive = over-forecast."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("AppError %s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": jsonable_encoder(exc.details)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"]}
            for e in exc.errors()
        ]
        first = problems[0] if problems else {"field": "", "message": "invalid request"}
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid request: {first['field']} {first['message']}".replace("  ", " ").strip(),
                    "details": {"problems": problems},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Unexpected server error", "details": {}}},
        )

    for r in (health.router, calibrations.router, decisions.router, coverage.router):
        app.include_router(r)
    return app


def _default_app() -> FastAPI:
    return create_app()


# `uvicorn app.main:app`
app = _default_app()
