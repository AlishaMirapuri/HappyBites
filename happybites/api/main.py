"""FastAPI application entry point."""

import logging

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from happybites.config import settings


def setup_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.environment == "development":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    # Silence SQLAlchemy echo in non-dev environments
    if settings.environment != "development":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


setup_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, seed sources, start scheduler. Shutdown: stop scheduler."""
    from happybites.db.engine import init_db
    from happybites.db.models import Source
    from happybites.db.engine import SessionLocal
    from happybites.ingestion.scheduler import start_scheduler, stop_scheduler

    logger.info("startup", environment=settings.environment)
    init_db()

    # Ensure default sources exist
    db = SessionLocal()
    try:
        _ensure_sources(db)
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()
    logger.info("shutdown")


def _ensure_sources(db) -> None:
    """Insert default sources if they don't exist yet."""
    from happybites.db.models import Source

    defaults = [
        Source(
            name="dealnews",
            type="rss",
            base_url="https://dealnews.com/rss/deals.rss",
            fetch_interval=7200,
            is_active=True,
        ),
        Source(
            name="reddit",
            type="api",
            base_url="https://www.reddit.com/r/deals",
            fetch_interval=3600,
            is_active=True,
        ),
        Source(
            name="seed",
            type="seed",
            base_url=None,
            fetch_interval=86400,
            is_active=True,
        ),
    ]
    for source in defaults:
        existing = db.query(Source).filter(Source.name == source.name).first()
        if not existing:
            db.add(source)
    db.commit()


app = FastAPI(
    title=settings.app_name,
    description="AI-powered deal discovery API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from happybites.api.routers import admin, deals, events, health, ingest, sources, venues  # noqa: E402

app.include_router(deals.router, prefix="/deals", tags=["deals"])
app.include_router(venues.router, prefix="/venues", tags=["venues"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(sources.router, prefix="/sources", tags=["sources"])
app.include_router(health.router, tags=["health"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
