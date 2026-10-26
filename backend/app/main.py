"""
FastAPI Main Application Entrypoint.

Features:
- Modern `lifespan` Context Manager (clean startup/shutdown sequence).
- Async Database Table Initialization.
- Background Redis Listener Task.
- CORS Middleware configured for React frontend communication.
- Global Exception and Logging Configuration.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.redis import close_redis, start_redis_listener
from app.services.poller import start_flight_poller


# Configure application-wide structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("reroute.main")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI Lifespan Handler.
    
    Replaces deprecated `@app.on_event("startup")` and `@app.on_event("shutdown")`.
    
    1. Everything before the `yield` runs when the server STARTS:
       - Connects to database and ensures tables are created (`init_db()`).
       - Creates an asyncio Event flag (`stop_event`) to signal background workers.
       - Starts the Redis listener worker as a concurrent background task.
       
    2. The `yield` pauses here while the server is alive and serving HTTP requests.
    
    3. Everything after the `yield` runs when the server SHUTS DOWN (e.g., Ctrl+C or SIGTERM):
       - Sets `stop_event` so the Redis listener loop exits cleanly.
       - Awaits listener task completion.
       - Closes connection pools.
    """
    logger.info("=== Starting %s (%s) ===", settings.PROJECT_NAME, settings.ENVIRONMENT)
    
    # 1. Initialize Database Schema
    logger.info("Initializing database tables...")
    await init_db()
    logger.info("Database initialized successfully.")

    # 1b. Auto-seed demo data if AUTO_SEED=true (creates demo records if database is empty/fresh)
    if settings.AUTO_SEED:
        logger.info("AUTO_SEED=true: checking and executing idempotent demo seeder...")
        try:
            from scripts.seed_demo import seed_demo
            await seed_demo()
        except ImportError:
            try:
                from backend.scripts.seed_demo import seed_demo
                await seed_demo()
            except Exception as e:
                logger.error("Auto-seed failed: %s", e)
        except Exception as e:
            logger.error("Auto-seed failed: %s", e)

    # 2. Start Background Redis Consumer Task & Poller Task
    stop_event = asyncio.Event()
    listener_task = asyncio.create_task(
        start_redis_listener(stop_event),
        name="redis_event_listener"
    )
    poller_task = asyncio.create_task(
        start_flight_poller(stop_event),
        name="flight_status_poller"
    )

    # Server is now ready to receive traffic
    yield

    # Shutdown sequence
    logger.info("=== Shutting down %s ===", settings.PROJECT_NAME)
    stop_event.set()
    
    try:
        # Wait up to 3 seconds for background tasks to cleanly finish
        await asyncio.wait_for(
            asyncio.gather(listener_task, poller_task, return_exceptions=True),
            timeout=3.0
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Background tasks cancelled during shutdown.")

    # Close Redis client
    await close_redis()
    logger.info("Shutdown complete.")



def create_application() -> FastAPI:
    """
    Application Factory pattern.
    Creates and configures the FastAPI instance.
    """
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="Autonomous Travel-Disruption Concierge API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS for local React development from settings.CORS_ORIGINS
    cors_env = settings.CORS_ORIGINS
    allowed_origins = [o.strip() for o in cors_env.split(",") if o.strip()] if cors_env else ["http://localhost:3000", "http://localhost:5173", "*"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    application.include_router(api_v1_router)

    @application.get("/", tags=["Root"])
    async def root():
        return {
            "message": f"Welcome to {settings.PROJECT_NAME}",
            "docs": "/docs",
            "health": "/api/v1/health"
        }

    return application


app = create_application()
