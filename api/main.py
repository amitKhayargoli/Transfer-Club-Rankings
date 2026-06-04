"""
FastAPI application entry point.

Run with: uvicorn api.main:app --reload
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import API_HOST, API_PORT
from api.database import init_db
from api.routers import clubs, players, transfers, dashboard, pipeline, search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup."""
    logger.info("Initializing database tables...")
    try:
        await init_db()
        logger.info("Database tables ready.")
    except Exception as e:
        logger.warning("Could not initialize database: %s", e)
        logger.warning("Run POST /api/pipeline/run to load data first.")
    yield


app = FastAPI(
    title="Transfer ROI Rankings API",
    description="Analyze football transfers across European competitions, "
                "calculate ROI for each transfer, and rank clubs by their "
                "ability to buy low and sell high.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(clubs.router)
app.include_router(players.router)
app.include_router(transfers.router)
app.include_router(dashboard.router)
app.include_router(pipeline.router)
app.include_router(search.router)


@app.get("/")
async def root():
    return {
        "name": "Transfer ROI Rankings API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "clubs": "/api/clubs",
            "players": "/api/players",
            "transfers": "/api/transfers",
            "dashboard": "/api/dashboard/stats",
            "top_clubs": "/api/dashboard/top-clubs",
            "pipeline": "/api/pipeline/run",
            "search": "/api/search?q=",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=True)
