"""FastAPI application: REST API, React build and in-process scheduler in one process.

Run with a single uvicorn worker, otherwise the scheduler jobs run once per worker.
"""

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from boursy import __version__
from boursy.api import auth, stocks, system
from boursy.config import Settings, get_settings
from boursy.data.provider import MarketDataProvider
from boursy.data.yahoo import YahooProvider
from boursy.db.session import init_db, new_session
from boursy.scheduler.jobs import start_scheduler
from boursy.universe.seed import seed_universe

log = logging.getLogger("boursy")

SESSION_MAX_AGE_S = 30 * 24 * 3600


def setup_logging(settings: Settings) -> None:
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_dir / "boursy.log", maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream)
    logging.getLogger("alembic").setLevel(logging.WARNING)  # boursy.db.migrate logs the outcome
    root.setLevel(settings.log_level)


def create_app(settings: Settings | None = None, provider: MarketDataProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    provider = provider or YahooProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings)
        init_db(settings.db_url)
        with new_session() as s:
            added = seed_universe(s)
        if added:
            log.info("Seeded universe with %d stocks", added)
        if not settings.app_password:
            log.warning("BOURSY_APP_PASSWORD is empty: login is impossible until it is set")
        app.state.scheduler = start_scheduler(settings, provider) if settings.scheduler_enabled else None
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)

    app = FastAPI(title="Boursy", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.provider = provider
    app.state.scheduler = None
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.resolved_session_secret(),
        session_cookie="boursy_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.include_router(system.public)
    app.include_router(auth.router)
    app.include_router(stocks.router)
    app.include_router(system.router)
    mount_frontend(app, settings)
    return app


def mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the React build with SPA fallback to index.html (only when the build exists)."""
    static_dir = settings.static_dir.resolve()
    index = static_dir / "index.html"
    if not index.is_file():
        log.info("No frontend build in %s; API only", static_dir)
        return
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(static_dir):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
