"""
Refresh orchestrator — coordinates fetcher, calculator, and database.
Called by the scheduler and also on startup.
"""

import logging
from datetime import datetime

from backend.calculator import calculate_implied_price, compare_prices
from backend.database import save_snapshot
from backend.fetcher import fetch_all
from backend import notifier

logger = logging.getLogger(__name__)


def do_refresh() -> dict:
    """
    Fetches all data, calculates implied price, saves to DB, returns result dict.
    """
    raw = fetch_all()

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
        "captured_at": datetime.utcnow(),
        "btc_price": raw["btc_price"],
        "btc_amount": raw["btc_amount"],
        "debt_usd": raw["debt_usd"],
        "preferred_usd": raw["preferred_usd"],
        "cash_usd": raw["cash_usd"],
        "diluted_shares": raw["diluted_shares"],
        "current_price": raw["current_price"],
        "implied_price": calc["implied_price"],
        "btc_value_usd": calc["btc_value_usd"],
        "equity_value_usd": calc["equity_value_usd"],
        "discount_pct": comparison["discount_pct"],
        "is_undervalued": comparison["is_undervalued"],
        "signal": comparison["signal"],
        "data_date": raw.get("data_date", ""),
    }

    save_snapshot(snapshot)
    notifier.maybe_notify(snapshot)  # send Telegram if undervalued

    return {
        **snapshot,
        "signal_emoji": comparison["signal_emoji"],
        "classification": comparison["classification"],
        "fetched_at_et": raw.get("fetched_at_et", ""),
        "market_cap_usd": raw.get("market_cap_usd", 0),
    }
