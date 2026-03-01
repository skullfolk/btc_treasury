"""
Refresh orchestrator — coordinates fetcher, calculator, database, and notifier.
Supports multiple companies via a single do_refresh(company) call.
do_refresh_all() loops over every supported company.
"""

import logging
from datetime import datetime

from backend.calculator import calculate_implied_price, compare_prices
from backend.database import save_snapshot
from backend.fetcher import fetch_all, SUPPORTED_COMPANIES
from backend import notifier

logger = logging.getLogger(__name__)


def do_refresh(company: str = "MSTR") -> dict:
    """
    Fetch, calculate, persist, and optionally notify for one company.
    Returns the full enriched snapshot dict (including ephemeral fields
    like signal_emoji, fetched_at_et that are NOT stored in DB).
    """
    company = company.upper()
    logger.info("=== Refresh START: %s ===", company)

    raw = fetch_all(company)

    calc = calculate_implied_price(
        btc_price=raw["btc_price"],
        btc_amount=raw["btc_amount"],
        debt=raw["debt_usd"],
        preferred=raw["preferred_usd"],
        cash=raw["cash_usd"],
        diluted_shares=raw["diluted_shares"],
    )

    comparison = compare_prices(
        current_price=raw["current_price"],
        implied_price=calc["implied_price"],
    )

    snapshot = {
        "captured_at":    datetime.utcnow(),
        "btc_price":      raw["btc_price"],
        "btc_amount":     raw["btc_amount"],
        "debt_usd":       raw["debt_usd"],
        "preferred_usd":  raw["preferred_usd"],
        "cash_usd":       raw["cash_usd"],
        "diluted_shares": raw["diluted_shares"],
        "current_price":  raw["current_price"],
        "implied_price":  calc["implied_price"],
        "btc_value_usd":  calc["btc_value_usd"],
        "equity_value_usd": calc["equity_value_usd"],
        "discount_pct":   comparison["discount_pct"],
        "is_undervalued": comparison["is_undervalued"],
        "signal":         comparison["signal"],
        "data_date":      raw.get("data_date", ""),
    }

    save_snapshot(snapshot, company=company)
    notifier.maybe_notify(snapshot, company=company)

    logger.info(
        "=== Refresh DONE: %s  price=$%.2f  implied=$%.2f  signal=%s ===",
        company, raw["current_price"], calc["implied_price"], comparison["signal"]
    )

    # Return enriched dict (includes non-DB ephemeral fields)
    return {
        **snapshot,
        "company":         company,
        "ticker":          raw.get("ticker", company),
        "company_name":    raw.get("company_name", company),
        "signal_emoji":    comparison["signal_emoji"],
        "classification":  comparison["classification"],
        "fetched_at_et":   raw.get("fetched_at_et", ""),
        "market_cap_usd":  raw.get("market_cap_usd", 0),
    }


def do_refresh_all() -> dict[str, dict]:
    """
    Refresh every supported company. Returns dict keyed by company ticker.
    Errors in one company do NOT abort others.
    """
    results = {}
    for company in SUPPORTED_COMPANIES:
        try:
            results[company] = do_refresh(company)
        except Exception as exc:
            logger.error("Refresh failed for %s: %s", company, exc, exc_info=True)
    return results
