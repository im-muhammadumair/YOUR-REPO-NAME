"""MTM HR Agent API - application entrypoint.

This module:
  1. Builds the FastAPI application object.
  2. Configures security-related middleware (CORS).
  3. Includes the authentication and domain routers.
  4. Seeds roles/permissions/users on startup.

It does NOT contain domain or business logic - those live in auth/, database/
and routes/. Running this file starts the server:  python main.py
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import routes as auth_routes
from auth.refresh_service import cleanup_expired, cleanup_sessions
from auth.rbac import seed_roles_and_permissions

from config import ALLOWED_ORIGINS, GEMINI_API_KEY
from database.connection import Base, engine, get_db
from database.migrate_ai import run_migrations as run_ai_migrations
from database.seed_users import seed_users
from routes import accounts, attendance, chat, documents, employees, leaves, payroll

_log = logging.getLogger("refresh_cleanup")

# How often the background cleanup runs (seconds).
_CLEANUP_INTERVAL = 3600  # 1 hour


async def _periodic_session_cleanup():
    """Background task that deletes expired refresh sessions every hour.

    Runs until the app shuts down. Catches exceptions so a single failure
    never kills the task.
    """
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        try:
            db = next(get_db())
            try:
                deleted = cleanup_expired(db)
                if deleted:
                    _log.info("periodic cleanup: deleted %d expired sessions", deleted)
            finally:
                db.close()
        except Exception as exc:
            _log.warning("periodic cleanup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks for the application.

    On startup the authentication tables (users, roles, permissions,
    refresh_sessions) are ensured to exist and then seeded so the system is
    ready to authenticate users. The Gemini model registry is discovered from
    the live API so the RAG layer never depends on a hardcoded model name.

    Takes: app - the FastAPI application instance.
    Returns: a context manager that yields during the app's lifetime.
    Side effect: creates and seeds the authentication tables on startup.
    """
    Base.metadata.create_all(bind=engine)

    # Ensure the documents table has the AI/RAG columns (idempotent, additive).
    # New columns are added if missing; no tables or existing data are touched.
    run_ai_migrations()

    # Discover the currently available Gemini models and bind the health
    # tracker. This is resilient: if there is no API key or discovery fails,
    # the application still starts (generation resolves models lazily).
    if GEMINI_API_KEY:
        try:
            from google import genai
            from rag.model_health import health
            from rag.model_registry import discover, registry

            client = genai.Client(api_key=GEMINI_API_KEY)
            discovered = discover(client)
            registry._models = discovered._models
            registry._order = discovered._order
            health.bind(registry)
        except Exception:
            pass

    db = next(get_db())
    try:
        seed_roles_and_permissions(db)
        seed_users(db)
        cleanup_sessions(db)   # full purge on startup
    finally:
        db.close()

    # Start periodic background cleanup (deletes expired rows every hour)
    cleanup_task = asyncio.create_task(_periodic_session_cleanup())

    yield

    # Shutdown: cancel the background cleanup task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(title="MTM HR Agent API", lifespan=lifespan)

# Allow the configured frontend origins to talk to this API. JWT bearer auth is
# used (no cookies), so credentials do not need to be shared cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up the authentication and domain routers.
app.include_router(auth_routes.router)
app.include_router(accounts.router)
app.include_router(employees.router)
app.include_router(attendance.router)
app.include_router(leaves.router)
app.include_router(payroll.router)
app.include_router(documents.router)
app.include_router(chat.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
# Returns a simple liveness response used by scripts to check the server.
# Takes: none.
# Returns: a dict with a status of "ok".
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os

    import uvicorn

    # Number of worker processes. Raise this (e.g. WEB_CONCURRENCY=4) so the
    # backend can serve many concurrent users. Uvicorn requires the app as an
    # import string when running multiple workers.
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        workers=workers,
    )
