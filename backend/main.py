"""
FastAPI application entry point.
Serves the static frontend and exposes REST API endpoints.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.database import get_history, get_latest_snapshot, init_db
from backend.refresh import do_refresh
from backend.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  App lifespan
# --------------------------------------------------------------------------- #

_cache: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initialising database…")
    init_db()

    # Load last snapshot from DB into cache
    latest = get_latest_snapshot()
    if latest:
        _cache.update(latest)
        logger.info("Loaded latest snapshot from DB (captured %s)", latest.get("captured_at"))
    else:
        logger.info("No existing snapshot — running initial fetch…")
        try:
            result = do_refresh()
            _cache.update(result)
        except Exception as exc:
            logger.error("Initial fetch failed: %s", exc)

    start_scheduler()
    yield

    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="BTC Treasury Implied Value",
    description="Tracks MSTR implied share price based on BTC holdings",
    version="1.0.0",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------- #
#  Static frontend
# --------------------------------------------------------------------------- #

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# --------------------------------------------------------------------------- #
#  API endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/data")
async def get_data():
    """Returns the latest calculated snapshot."""
    latest = get_latest_snapshot()
    if not latest:
        if not _cache:
            raise HTTPException(status_code=503, detail="Data not yet available. Please wait for the initial fetch to complete.")
        return JSONResponse(_cache)
    return JSONResponse(latest)


@app.get("/api/history")
async def get_history_data(limit: int = 90):
    """Returns historical snapshots (default last 90 days)."""
    limit = max(1, min(limit, 365))
    rows = get_history(limit)
    return JSONResponse(rows)


@app.post("/api/refresh")
async def manual_refresh():
    """Triggers a manual data refresh (useful for testing)."""
    try:
        result = do_refresh()
        _cache.update(result)
        return JSONResponse({"status": "ok", "implied_price": result["implied_price"]})
    except Exception as exc:
        logger.error("Manual refresh error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "utc": datetime.now(timezone.utc).isoformat(),
        "has_data": bool(get_latest_snapshot()),
    }
