from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import ROOT, Settings
from app.errors import DomainError
from app.modules.m7_batches.handler import router as batch_router
from app.store import Store
from app.web import router as web_router


def create_app(settings=None):
    settings = settings or Settings.from_env()
    store = Store(settings.db_file)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="轴组称重工作台", lifespan=lifespan)
    app.state.settings, app.state.store = settings, store

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError):
        return JSONResponse({"error": error.payload()}, status_code=error.status)

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
    app.include_router(api_router)
    app.include_router(batch_router)
    app.include_router(web_router)
    return app


app = create_app()
