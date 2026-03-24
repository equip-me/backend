import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise import Tortoise

from app.core.config import get_settings
from app.core.database import get_tortoise_config
from app.core.exceptions import AppError, app_error_handler
from app.listings.models import ListingCategory
from app.users.router import router as users_router

logger = logging.getLogger(__name__)

SEED_CATEGORIES = [
    "Спецтехника",
    "Промышленное оборудование",
    "Контрактное производство",
    "Выставочное оборудование",
]


async def _seed_categories() -> None:
    if await ListingCategory.exists():
        return
    for name in SEED_CATEGORIES:
        await ListingCategory.create(name=name, verified=True)
    logger.info("Seeded %d listing categories", len(SEED_CATEGORIES))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    config = get_tortoise_config()
    await Tortoise.init(config=config)
    await _seed_categories()
    yield
    await Tortoise.close_connections()


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)
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
    )

    application.add_exception_handler(AppError, _handle_app_error)
    application.include_router(users_router)

    return application


app = create_app()
