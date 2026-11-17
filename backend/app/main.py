from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.services import chat_model, disease_model


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # The models are loaded once here; without them the API still starts (503 on those calls).
    disease_model.load_at_startup()
    chat_model.load_at_startup()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ARISETO API", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    # In development the API also serves the PWA, so both share http://localhost:8000.
    # Mounted last so /api/v1 and /docs take precedence.
    if settings.is_development and settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app


app = create_app()
