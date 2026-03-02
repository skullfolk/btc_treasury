"""
BTC Treasury Implied Share Price Calculator

Formula:
  (Fully Diluted Shares × Implied Price) + Debt + Preferred − Cash = BTC Price × BTC Amount
  ∴ Implied Price = (BTC Price × BTC Amount − Debt − Preferred + Cash) / Fully Diluted Shares

All monetary values must be in USD (not millions) when passed in.
"""


def calculate_implied_price(
    btc_price: float,
    btc_amount: float,
    debt: float,
    preferred: float,
    cash: float,
    diluted_shares: float,
) -> dict:
    """
    Returns a dict with implied_price and supporting metrics.
    All values in raw USD.
    """
    if diluted_shares <= 0:
        raise ValueError("diluted_shares must be positive")

    btc_value = btc_price * btc_amount
    net_non_btc = debt + preferred - cash  # liabilities minus cash
    equity_value = btc_value - net_non_btc
    implied_price = equity_value / diluted_shares

    return {
        "btc_value_usd": btc_value,
        "net_non_btc_usd": net_non_btc,
        "equity_value_usd": equity_value,
        "implied_price": implied_price,
    }


def compare_prices(current_price: float, implied_price: float) -> dict:
    """
    Compares current market price against implied BTC-backed fair value.
    Returns signal, discount/premium percentage, and classification.
    """
    if implied_price <= 0:
        return {
            "signal": "N/A",
            "signal_emoji": "❓",
            "discount_pct": 0.0,
            "is_undervalued": False,
            "classification": "unknown",
        }

    if current_price <= 0:
        return {
            "signal": "N/A",
            "signal_emoji": "❓",
            "discount_pct": 0.0,
            "is_undervalued": False,
            "classification": "unknown",
        }

    diff_pct = ((implied_price - current_price) / current_price) * 100

    if current_price <= implied_price:
        signal = "UNDERVALUED"
        emoji = "✅"
        classification = "undervalued"
    elif diff_pct > -5:  # within 5% above
        signal = "FAIR VALUE"
        emoji = "⚖️"
        classification = "fair"
    else:
        signal = "OVERVALUED"
        emoji = "🔴"
        classification = "overvalued"

    return {
        "signal": signal,
        "signal_emoji": emoji,
        "discount_pct": round(diff_pct, 2),   # positive = discount, negative = premium
        "is_undervalued": current_price <= implied_price,
        "classification": classification,
    }
