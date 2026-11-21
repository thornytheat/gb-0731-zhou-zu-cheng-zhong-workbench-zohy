import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import ROOT, Settings
from app.errors import DomainError
from app.modules.m7_batches.handler import router as batch_router
from app.modules.m8_archive.archive_store import ArchiveStore
from app.modules.m8_archive.handler import router as archive_router
from app.store import Store
from app.web import router as web_router


def create_app(settings=None):
    settings = settings or Settings.from_env()
    store = Store(settings.db_file)
    archive = ArchiveStore(settings.archive_db_file)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        archive.initialize()
        yield

    app = FastAPI(title="轴组称重工作台", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.archive = archive
    app.state.archive_hmac_key = os.getenv("WEIGH_COLD_HMAC")

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError):
        return JSONResponse({"error": error.payload()}, status_code=error.status)

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
    app.include_router(api_router)
    app.include_router(batch_router)
    app.include_router(archive_router)
    app.include_router(web_router)
    return app


app = create_app()
