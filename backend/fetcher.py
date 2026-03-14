"""
Data fetcher — pulls all required inputs for each supported company.

Supported companies
  MSTR  MicroStrategy / Strategy  https://api.strategy.com + strategy.com/shares
  ASST  Strive Asset Management   https://treasury.strive.com (scraped)

Public interface
  fetch_all(company: str) -> dict   # merged, normalised dict ready for calculator
"""

import logging
import re
from datetime import datetime
from typing import Any

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd"
)
BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

# Strategy / MSTR
STRATEGY_KPI_URL    = "https://api.strategy.com/btc/mstrKpiData"
STRATEGY_SHARES_URL = "https://www.strategy.com/shares"

# Strive / ASST
STRIVE_HOME_URL   = "https://treasury.strive.com/?tab=home"
STRIVE_CREDIT_URL = "https://treasury.strive.com/?tab=credit"
STRIVE_SHARES_URL = "https://treasury.strive.com/?tab=shares"


# ===========================================================================
#  Shared helpers
# ===========================================================================

def _get(url: str, timeout: int = 20) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


def _soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(_get(url).text, "lxml")


def _parse_num(text: str) -> float:
    """Strip currency symbols, commas, spaces and return float."""
    cleaned = re.sub(r"[,$€£\s]", "", str(text).strip())
    if cleaned in ("-", "–", "—", ""):
        return 0.0
    # Handle suffixes: B = billion, M = million, K = thousand
    m = re.fullmatch(r"([\d.]+)([BMKbmk]?)", cleaned)
    if m:
        val = float(m.group(1))
        suffix = m.group(2).upper()
        if suffix == "B":
            return val * 1_000_000_000
        if suffix == "M":
            return val * 1_000_000
        if suffix == "K":
            return val * 1_000
        return val
    raise ValueError(f"Cannot parse number: {text!r}")


def fetch_btc_price() -> float:
    """Live BTC/USD. Primary: CoinGecko. Fallback: Binance."""
    try:
        resp = requests.get(COINGECKO_URL, timeout=10)
        resp.raise_for_status()
        return float(resp.json()["bitcoin"]["usd"])
    except Exception as exc:
        logger.warning("CoinGecko failed (%s), trying Binance…", exc)
    resp = requests.get(BINANCE_URL, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])


# ===========================================================================
#  MSTR / Strategy
# ===========================================================================

def _parse_mstr_number(val: Any) -> float:
    """Strategy API values are in $M — convert to raw USD."""
    return float(str(val).replace(",", "")) * 1_000_000


def _fetch_mstr_kpi() -> dict:
    resp = _get(STRATEGY_KPI_URL, timeout=15)
    d = resp.json()[0]
    return {
        "current_price":  float(d["ufPrice"]),
        "debt_usd":       _parse_mstr_number(d["debt"]),
        "preferred_usd":  _parse_mstr_number(d["pref"]),
        "market_cap_usd": _parse_mstr_number(d["marketCap"]),
        "ent_val_usd":    _parse_mstr_number(d["entVal"]),
        "data_date":      d.get("timeStamp", ""),
    }


def _fetch_mstr_shares_and_btc() -> dict:
    soup = _soup(STRATEGY_SHARES_URL)
    diluted_shares = None
    btc_amount     = None

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            if re.search(r"assumed diluted shares outstanding|total assumed diluted", label, re.I):
                raw = re.sub(r"[,\s]", "", cells[-1].get_text(strip=True))
                if raw:
                    diluted_shares = float(raw) * 1_000   # values in '000s
            if re.search(r"total btc", label, re.I):
                raw = re.sub(r"[,\s]", "", cells[-1].get_text(strip=True))
                if raw:
                    btc_amount = float(raw)

    # Fallback: __NEXT_DATA__
    if diluted_shares is None or btc_amount is None:
        import json as _json
        nd = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            soup.get_text(separator=" "), re.S
        )
        if nd:
            try:
                page_props = _json.loads(nd.group(1)).get("props", {}).get("pageProps", {})
                data = page_props.get("sharesData") or page_props.get("data")
                if isinstance(data, list) and data:
                    latest = data[-1]
                    if diluted_shares is None and "assumedDilutedShares" in latest:
                        diluted_shares = float(latest["assumedDilutedShares"]) * 1_000
                    if btc_amount is None and "totalBtc" in latest:
                        btc_amount = float(latest["totalBtc"])
            except Exception as exc:
                logger.warning("MSTR __NEXT_DATA__ fallback failed: %s", exc)

    if diluted_shares is None:
        raise RuntimeError("Could not parse MSTR Fully Diluted Shares from strategy.com/shares")
    if btc_amount is None:
        raise RuntimeError("Could not parse MSTR Total BTC from strategy.com/shares")

    return {"diluted_shares": diluted_shares, "btc_amount": btc_amount}


def _derive_cash_from_ev(market_cap_usd: float, debt_usd: float,
                          preferred_usd: float, ent_val_usd: float) -> float:
    """EV = MarketCap + Debt + Preferred − Cash  ∴ Cash = MC+D+P−EV."""
    cash = market_cap_usd + debt_usd + preferred_usd - ent_val_usd
    if cash > 0:
        logger.info("Cash derived from EV formula: $%.0fM", cash / 1_000_000)
        return cash
    logger.warning("EV-derived cash non-positive (%.0f) — using 0", cash)
    return 0.0


def fetch_mstr() -> dict:
    """Fetch all MSTR inputs. Returns normalised dict."""
    logger.info("[MSTR] Fetching KPI data…")
    kpi = _fetch_mstr_kpi()

    logger.info("[MSTR] Fetching shares & BTC holdings…")
    shares = _fetch_mstr_shares_and_btc()

    cash = _derive_cash_from_ev(
        market_cap_usd=kpi["market_cap_usd"],
        debt_usd=kpi["debt_usd"],
        preferred_usd=kpi["preferred_usd"],
        ent_val_usd=kpi["ent_val_usd"],
    )

    return {
        "company":        "MSTR",
        "ticker":         "MSTR",
        "company_name":   "Strategy (MicroStrategy)",
        "current_price":  kpi["current_price"],
        "debt_usd":       kpi["debt_usd"],
        "preferred_usd":  kpi["preferred_usd"],
        "market_cap_usd": kpi["market_cap_usd"],
        "cash_usd":       cash,
        "data_date":      kpi["data_date"],
        "diluted_shares": shares["diluted_shares"],
        "btc_amount":     shares["btc_amount"],
    }


# ===========================================================================
#  ASST / Strive  —  uses data.strategytracker.com versioned JSON API
# ===========================================================================
#
# The treasury.strive.com site is client-side rendered (no static HTML data).
# The real data comes from a versioned GCS-backed JSON endpoint:
#   Step 1: GET https://data.strategytracker.com/latest.json
#           → {"version": "20260301T130352Z", ...}
#   Step 2: GET https://data.strategytracker.com/ASST.v{version}.json
#           → full company metrics including shares, BTC, price, debt, cash
# ===========================================================================

STRATEGYTRACKER_LATEST = "https://data.strategytracker.com/latest.json"
STRATEGYTRACKER_CO_URL = "https://data.strategytracker.com/all.v{version}.json"


def _fetch_strategytracker(ticker: str) -> dict:
    """
    Fetch all company data from data.strategytracker.com.
    We fetch the 'all' payload because requesting specific tickers like '3350.T'
    directly returns a 403 Forbidden.
    """
    logger.info("[%s] Fetching latest version from strategytracker.com…", ticker)
    latest_resp = requests.get(STRATEGYTRACKER_LATEST, headers=HEADERS, timeout=15)
    latest_resp.raise_for_status()
    version = latest_resp.json()["version"]
    logger.info("[%s] StrategyTracker version: %s", ticker, version)

    url = STRATEGYTRACKER_CO_URL.format(version=version)
    logger.info("[%s] Fetching company data: %s", ticker, url)
    data_resp = requests.get(url, headers=HEADERS, timeout=15)
    data_resp.raise_for_status()
    return data_resp.json()


def fetch_strive() -> dict:
    """Fetch all Strive (ASST) inputs via strategytracker.com JSON API.

    JSON schema: { "companies": { "ASST": { "processedMetrics": {...} } } }
    """
    logger.info("[ASST] Fetching from StrategyTracker API…")
    raw = _fetch_strategytracker("ASST")

    # Navigate into the nested structure
    try:
        d = raw["companies"]["ASST"]["processedMetrics"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"[ASST] Unexpected StrategyTracker JSON shape: {exc}. "
            f"Top-level keys: {list(raw.keys())}"
        ) from exc

    # All monetary values are already in raw USD in the API response
    current_price  = float(d.get("stockPrice", 0) or 0)
    btc_amount     = float(d.get("latestBtcBalance", 0) or 0)
    # latestDilutedShares = Assumed Diluted Shares Outstanding (90M) as shown on treasury.strive.com
    diluted_shares = float(d.get("latestDilutedShares", 0) or 0)
    debt_usd       = float(d.get("latestDebt", 0) or 0)
    cash_usd       = float(d.get("latestCashBalance", 0) or 0)
    market_cap_usd = float(d.get("marketCapBasic", 0) or 0)

    # Preferred stock: sum notional USD from preferredStocks list
    preferred_usd = 0.0
    for ps in raw.get("companies", {}).get("ASST", {}).get("processedMetrics", {}).get(
        "preferredStocks", []
    ):
        preferred_usd += float(ps.get("notionalUSD", 0) or 0)

    logger.info(
        "[ASST] price=$%.2f  BTC=%.1f  effShares=%.0f  debt=$%.0fM  "
        "pref=$%.0fM  cash=$%.0fM  mktcap=$%.0fM",
        current_price, btc_amount, diluted_shares,
        debt_usd / 1e6, preferred_usd / 1e6, cash_usd / 1e6, market_cap_usd / 1e6,
    )

    return {
        "company":        "ASST",
        "ticker":         "ASST",
        "company_name":   "Strive Asset Management",
        "current_price":  current_price,
        "debt_usd":       debt_usd,
        "preferred_usd":  preferred_usd,
        "market_cap_usd": market_cap_usd,
        "cash_usd":       cash_usd,
        "data_date":      datetime.now(pytz.timezone("America/New_York")).strftime(
                              "%m/%d/%Y %I:%M %p ET"
                          ),
        "diluted_shares": diluted_shares,
        "btc_amount":     btc_amount,
    }


def fetch_metaplanet() -> dict:
    """Fetch all Metaplanet inputs via strategytracker.com JSON API.
    
    ticker = '3350.T'
    The default `stockPrice` is given in JPY. But `currentMarketCap` is already converted to USD.
    We derive the implied stock price in USD using `marketCapBasic` / `latestDilutedShares`.
    """
    logger.info("[META] Fetching from StrategyTracker API…")
    raw = _fetch_strategytracker("META")

    try:
        d = raw["companies"]["3350.T"]["processedMetrics"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"[META] Unexpected StrategyTracker JSON shape: {exc}") from exc

    btc_amount = float(d.get("latestBtcBalance", 0) or 0)
    diluted_shares = float(d.get("latestDilutedShares", 0) or 0)
    debt_usd = float(d.get("latestDebt", 0) or 0)
    cash_usd = float(d.get("latestCashBalance", 0) or 0)
    market_cap_usd = float(d.get("marketCapBasic", 0) or 0)

    # Derive USD stock price.
    current_price_usd = 0.0
    total_shares = float(d.get("latestTotalShares", 0) or 0)
    
    # marketCapBasic is calculated based on total outstanding shares, not diluted shares
    if total_shares > 0 and market_cap_usd > 0:
        current_price_usd = market_cap_usd / total_shares

    logger.info(
        "[META] price(usd)=$%.2f  BTC=%.1f  effShares=%.0f  debt=$%.0fM  "
        "cash=$%.0fM  mktcap=$%.0fM",
        current_price_usd, btc_amount, diluted_shares,
        debt_usd / 1e6, cash_usd / 1e6, market_cap_usd / 1e6,
    )

    return {
        "company":        "META",
        "ticker":         "3350.T",
        "company_name":   "Metaplanet Inc.",
        "current_price":  current_price_usd,
        "debt_usd":       debt_usd,
        "preferred_usd":  0.0,
        "market_cap_usd": market_cap_usd,
        "cash_usd":       cash_usd,
        "data_date":      datetime.now(pytz.timezone("America/New_York")).strftime(
                              "%m/%d/%Y %I:%M %p ET"
                          ),
        "diluted_shares": diluted_shares,
        "btc_amount":     btc_amount,
    }


# ===========================================================================
#  Public dispatcher
# ===========================================================================

_FETCHERS = {
    "MSTR": fetch_mstr,
    "ASST": fetch_strive,
    "META": fetch_metaplanet,
}

SUPPORTED_COMPANIES = list(_FETCHERS.keys())

# Metadata exposed via /api/companies
_COMPANY_META = [
    {
        "ticker":       "MSTR",
        "name":         "Strategy (MicroStrategy)",
        "color":        "#f7941d",
        "source_url":   "https://www.strategy.com/",
        "logo_char":    "M",
    },
    {
        "ticker":       "ASST",
        "name":         "Strive Asset Management",
        "color":        "#ffd740",
        "source_url":   "https://treasury.strive.com/",
        "logo_char":    "S",
    },
    {
        "ticker":       "META",
        "name":         "Metaplanet Inc.",
        "color":        "#ff4e6a",
        "source_url":   "https://metaplanet.jp/en",
        "logo_char":    "M",
    },
]


def fetch_all(company: str = "MSTR") -> dict:
    """
    Fetch all inputs for the given company, append live BTC price,
    and return a single dict ready for the calculator.

    Raises ValueError for unknown company keys.
    """
    key = company.upper().strip()
    if key not in _FETCHERS:
        raise ValueError(
            f"Unknown company {company!r}. Supported: {SUPPORTED_COMPANIES}"
        )

    raw = _FETCHERS[key]()

    logger.info("Fetching live BTC price…")
    btc_price = fetch_btc_price()
    raw["btc_price"] = btc_price

    et = pytz.timezone("America/New_York")
    raw["fetched_at_et"] = datetime.now(et).strftime("%Y-%m-%d %H:%M ET")

    return raw
