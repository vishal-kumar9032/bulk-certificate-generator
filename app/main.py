import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.database import Base, engine
from app.services.certificate_renderer import initialize_fonts
from app.services.processor import (
    init_executor,
    recover_incomplete_jobs,
    shutdown_executor,
)
from app.settings import settings

# Configure structured application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("bulk_cert_generator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Handles database table initialization, directory setup,
    thread pool lifecycle, and startup recovery.
    """
    logger.info("Initializing Bulk Certificate Generator application...")

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    # Ensure storage directory exists
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize fonts
    initialize_fonts()

    # Initialize worker thread pool
    init_executor(settings.WORKER_THREADS)

    # Recover any jobs left unfinished from unexpected crashes
    recover_incomplete_jobs()

    logger.info("Application startup completed successfully.")
    yield

    logger.info("Shutting down application...")
    shutdown_executor()
    logger.info("Application shutdown completed.")


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="Bulk Certificate Generator API",
        description=(
            "Asynchronous backend API for generating and downloading "
            "event and course certificates in bulk with per-item isolation."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register API v1 routes
    app.include_router(api_router)

    @app.get("/health", tags=["Health"], summary="Service Health Check")
    def health_check():
        """Health check endpoint for liveness and readiness probes."""
        return {"status": "ok"}

    return app


app = create_app()
