"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.errors import install_exception_handlers
from app.notify import build_mailer
from app.ratelimit import RateLimiter
from app.routers import admin_auth, admin_contracts, local_storage, public_signing
from app.services.consent import consent_template
from app.services.storage import LocalStorage, build_storage

API_PREFIX = "/api/v1"
API_ROUTERS = (admin_auth.router, admin_contracts.router, public_signing.router)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    consent_template(settings.consent_text_version)  # fail at startup, not at the first signer

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "session_factory"):
            engine = make_engine(settings.database_url)
            app.state.engine = engine
            app.state.session_factory = make_session_factory(engine)
        try:
            yield
        finally:
            owned: AsyncEngine | None = getattr(app.state, "engine", None)
            if owned is not None:
                await owned.dispose()

    app = FastAPI(
        title="Foodverse Contract Signing API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.storage = build_storage(settings)
    app.state.mailer = build_mailer(settings)
    app.state.rate_limiter = RateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_exception_handlers(app)
    for router in API_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    if isinstance(app.state.storage, LocalStorage):
        app.include_router(local_storage.router)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        # FastAPI adds a 422 to every operation with parameters; keep only the
        # responses each route declares so the schema mirrors openapi.yaml.
        for router in API_ROUTERS:
            for route in router.routes:
                if not isinstance(route, APIRoute) or not route.include_in_schema:
                    continue
                declared = {str(code) for code in route.responses}
                for method in route.methods or ():
                    op = schema["paths"].get(API_PREFIX + route.path, {}).get(method.lower())
                    if op and "422" not in declared:
                        op["responses"].pop("422", None)
        for unused in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(unused, None)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
