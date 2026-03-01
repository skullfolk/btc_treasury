"""
Data fetcher — pulls all required inputs from strategy.com and CoinGecko.

Sources:
  - https://api.strategy.com/btc/mstrKpiData  →  price, debt, preferred, marketCap
  - https://www.strategy.com/shares           →  fully diluted shares, BTC amount
  - https://www.strategy.com/                 →  USD Reserve (cash proxy)
  - CoinGecko public API                      →  live BTC/USD price
"""

import logging
import re
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

STRATEGY_KPI_URL = "https://api.strategy.com/btc/mstrKpiData"
STRATEGY_SHARES_URL = "https://www.strategy.com/shares"
STRATEGY_HOME_URL = "https://www.strategy.com/"
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd"
)
BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

# --------------------------------------------------------------------------- #
#  Public API — KPI data
# --------------------------------------------------------------------------- #

def fetch_kpi_data() -> dict:
    """
    Returns:
        current_price    float  MSTR share price (USD)
        debt_usd         float  total debt (USD)
        preferred_usd    float  total preferred stock (USD)
        market_cap_usd   float  market cap (USD)
    """
    resp = requests.get(STRATEGY_KPI_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()[0]  # list with one element

    def _parse(val) -> float:
        """Strip commas and cast to float. Values are in $M."""
        return float(str(val).replace(",", "")) * 1_000_000

    return {
        "current_price": float(data["ufPrice"]),   # already USD per share
        "debt_usd": _parse(data["debt"]),
        "preferred_usd": _parse(data["pref"]),
        "market_cap_usd": _parse(data["marketCap"]),
        "ent_val_usd": _parse(data["entVal"]),
        "data_date": data.get("timeStamp", ""),
    }


# --------------------------------------------------------------------------- #
#  Shares page scraper — fully diluted shares + BTC holdings
# --------------------------------------------------------------------------- #

def _parse_number(text: str) -> float:
    """Remove commas, spaces, dashes; return float (in thousands if applicable)."""
    cleaned = re.sub(r"[,\s]", "", text.strip())
    if cleaned in ("-", "–", "—", ""):
        return 0.0
    return float(cleaned)


def fetch_shares_and_btc() -> dict:
    """
    Scrapes strategy.com/shares for:
      - Fully Diluted Shares Outstanding (latest column, in thousands)
      - Total BTC (latest column, in whole BTC)

    Returns:
        diluted_shares  float  total shares (raw count, not thousands)
        btc_amount      float  total BTC held
    """
    resp = requests.get(STRATEGY_SHARES_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Look for the "Assumed Diluted Shares Outstanding" table
    # The table has the header row containing dates and a "Total BTC" row
    diluted_shares = None
    btc_amount = None

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for i, row in enumerate(rows):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            first_cell_text = cells[0].get_text(strip=True)

            # Fully diluted row is the LAST row before empty or section end
            # Strategy uses "Assumed Diluted Shares Outstanding" or similar total
            if re.search(r"assumed diluted shares outstanding|total assumed diluted", first_cell_text, re.I):
                # Last column has the most recent value
                last_val = cells[-1].get_text(strip=True)
                diluted_shares = _parse_number(last_val) * 1_000  # values are in '000s

            if re.search(r"total btc", first_cell_text, re.I):
                last_val = cells[-1].get_text(strip=True)
                btc_amount = _parse_number(last_val)

    # Fallback: look for JSON-LD or __NEXT_DATA__ if table parsing fails
    if diluted_shares is None or btc_amount is None:
        diluted_shares, btc_amount = _scrape_next_data(resp.text, diluted_shares, btc_amount)

    if diluted_shares is None:
        raise RuntimeError("Could not parse Fully Diluted Shares from strategy.com/shares")
    if btc_amount is None:
        raise RuntimeError("Could not parse Total BTC from strategy.com/shares")

    return {
        "diluted_shares": diluted_shares,
        "btc_amount": btc_amount,
    }


def _scrape_next_data(html: str, diluted_shares, btc_amount):
    """Fallback: parse __NEXT_DATA__ JSON embedded in the page."""
    import json
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        return diluted_shares, btc_amount
    try:
        data = json.loads(match.group(1))
        # Walk through the props to find BTC and shares tables
        page_props = data.get("props", {}).get("pageProps", {})
        shares_data = page_props.get("sharesData") or page_props.get("data")
        if shares_data and isinstance(shares_data, list):
            # Take the last (most recent) entry
            latest = shares_data[-1]
            if diluted_shares is None and "assumedDilutedShares" in latest:
                diluted_shares = float(latest["assumedDilutedShares"]) * 1_000
            if btc_amount is None and "totalBtc" in latest:
                btc_amount = float(latest["totalBtc"])
    except Exception as exc:
        logger.warning("__NEXT_DATA__ fallback failed: %s", exc)
    return diluted_shares, btc_amount


# --------------------------------------------------------------------------- #
#  Cash / USD Reserve scraper (homepage)
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  Cash / USD Reserve — derived from Enterprise Value formula
# --------------------------------------------------------------------------- #

def derive_cash(market_cap_usd: float, debt_usd: float,
               preferred_usd: float, ent_val_usd: float) -> float:
    """
    Derives USD Reserve (Cash) from the Enterprise Value formula:
      EV = MarketCap + Debt + Preferred − Cash
      ∴ Cash = MarketCap + Debt + Preferred − EV

    All inputs and output are in raw USD (not millions).
    Falls back to 0 if result is non-positive.
    """
    derived = market_cap_usd + debt_usd + preferred_usd - ent_val_usd
    if derived > 0:
        logger.info(
            "Cash (USD Reserve) derived from EV formula: $%.0fM",
            derived / 1_000_000
        )
        return derived
    logger.warning(
        "EV-derived cash is non-positive (%.0f) — using 0. "
        "Check MarketCap/Debt/Pref/EV values.", derived
    )
    return 0.0


# --------------------------------------------------------------------------- #
#  BTC Price
# --------------------------------------------------------------------------- #

def fetch_btc_price() -> float:
    """
    Fetches live BTC/USD price.
    Primary: CoinGecko. Fallback: Binance.
    """
    try:
        resp = requests.get(COINGECKO_URL, timeout=10)
        resp.raise_for_status()
        return float(resp.json()["bitcoin"]["usd"])
    except Exception as exc:
        logger.warning("CoinGecko failed (%s), trying Binance…", exc)

    resp = requests.get(BINANCE_URL, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])


# --------------------------------------------------------------------------- #
#  Aggregate fetch
# --------------------------------------------------------------------------- #

def fetch_all() -> dict:
    """
    Fetches all required data and returns a single merged dict ready
    for passing to the calculator.
    """
    logger.info("Fetching KPI data from strategy.com…")
    kpi = fetch_kpi_data()

    logger.info("Fetching shares & BTC holdings from strategy.com/shares…")
    shares = fetch_shares_and_btc()

    logger.info("Deriving USD Reserve (Cash) from EV formula…")
    cash = derive_cash(
        market_cap_usd=kpi["market_cap_usd"],
        debt_usd=kpi["debt_usd"],
        preferred_usd=kpi["preferred_usd"],
        ent_val_usd=kpi["ent_val_usd"],
    )

    logger.info("Fetching live BTC price…")
    btc_price = fetch_btc_price()

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)

    return {
        "current_price": kpi["current_price"],
        "debt_usd": kpi["debt_usd"],
        "preferred_usd": kpi["preferred_usd"],
        "market_cap_usd": kpi["market_cap_usd"],
        "data_date": kpi["data_date"],
        "diluted_shares": shares["diluted_shares"],
        "btc_amount": shares["btc_amount"],
        "cash_usd": cash,
        "btc_price": btc_price,
        "fetched_at_et": now_et.strftime("%Y-%m-%d %H:%M ET"),
    }
