import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise.contrib.fastapi import RegisterTortoise

from app.core.config import get_settings
from app.core.database import get_tortoise_config
from app.core.exceptions import AppError, app_error_handler
from app.listings.models import ListingCategory
from app.listings.router import router as listings_router
from app.observability import instrument_app, setup_observability, shutdown_observability
from app.observability.middleware import TraceIDMiddleware
from app.orders.router import router as orders_router
from app.organizations.router import router as organizations_router
from app.users.router import router as users_router

logger = logging.getLogger(__name__)


async def _seed_categories() -> None:
    if await ListingCategory.exists():
        return
    settings = get_settings()
    for name in settings.seed_categories:
        await ListingCategory.create(name=name, verified=True)
    logger.info("Seeded %d listing categories", len(settings.seed_categories))


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    setup_observability()
    config = get_tortoise_config()
    async with RegisterTortoise(
        application,
        config=config,
        generate_schemas=True,
    ):
        await _seed_categories()
        yield
    shutdown_observability()


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_app() -> FastAPI:
    application = FastAPI(title="Rental Platform", lifespan=lifespan)

    settings = get_settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allow_origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
        expose_headers=settings.cors.expose_headers,
    )

    if settings.observability.enabled:
        application.add_middleware(TraceIDMiddleware)
    instrument_app(application)

    application.add_exception_handler(AppError, _handle_app_error)
    application.include_router(users_router)
    application.include_router(organizations_router)
    application.include_router(listings_router)
    application.include_router(orders_router)

    return application


app = create_app()
