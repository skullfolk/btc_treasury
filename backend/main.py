"""
FastAPI application — serves the static frontend and REST API.
All data endpoints accept a `company` query param (default: MSTR).
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.database import get_history, get_latest_snapshot, init_db
from backend.fetcher import SUPPORTED_COMPANIES
from backend.refresh import do_refresh, do_refresh_all
from backend.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Per-company in-memory cache  {company: snapshot_dict}
# ---------------------------------------------------------------------------

_cache: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Initialising database…")
    init_db()

    # Pre-load last DB snapshot for each company so API responds immediately
    for company in SUPPORTED_COMPANIES:
        latest = get_latest_snapshot(company)
        if latest:
            _cache[company] = latest
            logger.info(
                "[%s] Loaded snapshot from DB (captured %s)",
                company, latest.get("captured_at")
            )
        else:
            logger.info("[%s] No snapshot in DB — running initial fetch…", company)
            try:
                result = do_refresh(company)
                _cache[company] = result
            except Exception as exc:
                logger.error("[%s] Initial fetch failed: %s", company, exc)

    start_scheduler()
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    stop_scheduler()


app = FastAPI(
    title="BTC Treasury Implied Value",
    description="Multi-company BTC treasury fair value tracker",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
#  Static frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open(os.path.join(FRONTEND_DIR, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ---------------------------------------------------------------------------
#  API helpers
# ---------------------------------------------------------------------------

def _validate_company(company: str) -> str:
    key = company.upper().strip()
    if key not in SUPPORTED_COMPANIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown company '{company}'. Supported: {SUPPORTED_COMPANIES}"
        )
    return key


# ---------------------------------------------------------------------------
#  API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/data")
async def get_data(company: str = Query(default="MSTR", description="Company ticker")):
    """Returns the latest calculated snapshot for a company."""
    key = _validate_company(company)
    latest = get_latest_snapshot(key)
    if latest:
        # Merge any ephemeral cache fields (signal_emoji etc.) missing from DB row
        return JSONResponse({**_cache.get(key, {}), **latest})
    if key in _cache and _cache[key]:
        return JSONResponse(_cache[key])
    raise HTTPException(
        status_code=503,
        detail=f"No data available for {key}. Please wait for the initial fetch."
    )


@app.get("/api/history")
async def get_history_data(
    company: str = Query(default="MSTR"),
    limit: int = Query(default=90, ge=1, le=365),
):
    """Returns historical snapshots for a company (default last 90 entries)."""
    key = _validate_company(company)
    rows = get_history(key, limit)
    return JSONResponse(rows)


@app.post("/api/refresh")
async def manual_refresh(
    company: str = Query(default="all", description="Company ticker or 'all'")
):
    """
    Trigger a manual data refresh.
    Pass ?company=MSTR, ?company=ASST, or ?company=all (default) to refresh all.
    """
    try:
        if company.lower() == "all":
            results = do_refresh_all()
            for key, result in results.items():
                _cache[key] = result
            return JSONResponse({
                "status": "ok",
                "refreshed": {k: v["signal"] for k, v in results.items()},
            })
        else:
            key = _validate_company(company)
            result = do_refresh(key)
            _cache[key] = result
            return JSONResponse({
                "status": "ok",
                "company": key,
                "implied_price": result["implied_price"],
                "signal": result["signal"],
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Manual refresh error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/test-report")
async def test_daily_report():
    """Manually trigger the daily Telegram report for testing."""
    from backend.refresh import do_refresh_all
    from backend.notifier import send_daily_report
    try:
        results = do_refresh_all()
        success = send_daily_report(results)
        return JSONResponse({
            "status": "ok",
            "sent": success,
        })
    except Exception as exc:
        logger.error("Test report error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/companies")
async def list_companies():
    """Returns metadata for all supported companies."""
    from backend.fetcher import _COMPANY_META
    return JSONResponse(_COMPANY_META)


@app.get("/api/health")
async def health():
    return {
        "status":    "ok",
        "version":   "2.0.0",
        "utc":       datetime.now(timezone.utc).isoformat(),
        "companies": {
            c: bool(get_latest_snapshot(c)) for c in SUPPORTED_COMPANIES
        },
    }
