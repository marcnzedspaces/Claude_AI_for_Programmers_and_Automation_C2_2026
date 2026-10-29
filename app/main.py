from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.config import get_settings
from app.core.errors import (
    register_exception_handlers,
    request_id_middleware,
)
from app.core.logging import (
    configure_logging,
    log_event,
)
from app.database import (
    close_database,
    connect_to_database,
    get_database,
)
from app.repositories.ticket_repository import TicketRepository
from app.repositories.usage_repository import UsageRepository


# Load settings once when the module is imported (fails early if a
# required setting such as APP_NAME is missing).
settings = get_settings()
configure_logging(settings.log_level)


# Runs code at application startup and shutdown. Everything before `yield`
# runs on startup; everything after it runs on shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open the shared MongoDB connection once, not on every request.
    await connect_to_database()

    database = get_database()

    # Create the MongoDB indexes (safe to run on every startup).
    await UsageRepository(database).ensure_indexes()
    await TicketRepository(database).ensure_indexes()

    # One structured log line to show that startup finished.
    log_event(
        "application_ready",
        environment=settings.app_env,
        faq_cache_enabled=settings.faq_cache_enabled,
    )

    try:
        # The application serves requests while paused here.
        yield
    finally:
        # Close the connection on shutdown, even if the app stopped with an error.
        await close_database()


# The FastAPI application. lifespan hooks in the startup/shutdown logic above.
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# Register the middleware and exception handlers.
app.middleware("http")(request_id_middleware)
register_exception_handlers(app)
# Register all the routes. The individual endpoints live in app/api/routes/
# and are combined in app/api/router.py.
app.include_router(api_router)
