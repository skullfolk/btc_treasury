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
#  ASST / Strive
# ===========================================================================

def _strive_find_kv(soup: BeautifulSoup, label_pattern: str) -> str | None:
    """
    Walk all text nodes to find a value paired with a matching label.
    The Strive site renders KPI boxes as label + value in sibling/parent elements.
    Strategy: find the label text, then look for the next numeric-looking sibling.
    """
    # Try finding by aria-label or title attributes first
    for el in soup.find_all(attrs={"aria-label": re.compile(label_pattern, re.I)}):
        text = el.get_text(strip=True)
        if text:
            return text

    # Walk all elements, find the label, take the adjacent value
    all_text = [(el, el.get_text(strip=True)) for el in soup.find_all(True)]
    for i, (el, txt) in enumerate(all_text):
        if re.search(label_pattern, txt, re.I) and len(txt) < 80:
            # Look in the next few siblings for a number
            for _, next_txt in all_text[i + 1: i + 6]:
                # Match values like $7.94, $500.61M, 13,131.8, 90,797,112
                if re.search(r"[\d,]+\.?\d*[BMK]?", next_txt) and len(next_txt) < 30:
                    return next_txt
    return None


def _strive_extract_metric(soup: BeautifulSoup, patterns: list[str]) -> float:
    """Try multiple label patterns and return first non-zero parsed value."""
    for pattern in patterns:
        raw = _strive_find_kv(soup, pattern)
        if raw:
            try:
                # Strip dollar signs and leading $ for _parse_num
                val = _parse_num(raw)
                if val != 0.0:
                    logger.debug("Strive metric %r = %s → %.4g", pattern, raw, val)
                    return val
            except ValueError:
                continue
    return 0.0


def _strive_scrape_home() -> dict:
    """Scrape treasury.strive.com Home tab for price, market cap, EV, BTC."""
    soup = _soup(STRIVE_HOME_URL)
    page_text = soup.get_text(separator="\n")

    # --- Structured extraction using regex on full page text -----------------
    def _find_after(label_re: str, text: str = page_text) -> str | None:
        """Find first $X or number that follows a label in page text."""
        m = re.search(
            r"(?i)" + label_re + r"[^$\d]{0,30}([$]?[\d,]+\.?\d*\s*[BMK]?)",
            text
        )
        return m.group(1).strip() if m else None

    def _extract(label_re: str) -> float:
        raw = _find_after(label_re)
        if raw:
            try:
                return _parse_num(raw)
            except ValueError:
                pass
        return 0.0

    # Stock price — look for "Stock Price" or a prominent small number near ASST
    current_price  = _extract(r"stock\s*price|share\s*price|ASST\s*price")
    market_cap_usd = _extract(r"market\s*cap")
    ent_val_usd    = _extract(r"enterprise\s*value|EV\b")
    btc_amount     = _extract(r"bitcoin\s*holdings?|btc\s*holdings?|total\s*btc")
    btc_value_usd  = _extract(r"bitcoin\s*nav|btc\s*nav|btc\s*value|bitcoin\s*value")

    # Fallback: pattern-match specific KPI boxes in the HTML
    # The site renders data in <div> with labels and values
    for block in soup.find_all(["div", "section", "article"]):
        block_txt = block.get_text(separator=" ", strip=True)
        if len(block_txt) > 300:
            continue  # skip large containers

        if current_price == 0 and re.search(r"stock\s*price|share\s*price", block_txt, re.I):
            m = re.search(r"\$?([\d]+\.[\d]{2})\b", block_txt)
            if m:
                current_price = float(m.group(1))

        if market_cap_usd == 0 and re.search(r"market\s*cap", block_txt, re.I):
            m = re.search(r"\$?([\d,]+\.?\d*)\s*M", block_txt)
            if m:
                market_cap_usd = float(m.group(1).replace(",", "")) * 1_000_000

        if ent_val_usd == 0 and re.search(r"enterprise\s*value", block_txt, re.I):
            m = re.search(r"\$?([\d,]+\.?\d*)\s*M", block_txt)
            if m:
                ent_val_usd = float(m.group(1).replace(",", "")) * 1_000_000

        if btc_amount == 0 and re.search(r"bitcoin\s*holdings?|₿", block_txt, re.I):
            m = re.search(r"([\d,]+\.?\d*)\s*₿", block_txt)
            if m:
                btc_amount = float(m.group(1).replace(",", ""))

    logger.info(
        "[ASST] Home: price=$%.2f  mktcap=$%.0fM  EV=$%.0fM  BTC=%.1f",
        current_price, market_cap_usd / 1e6, ent_val_usd / 1e6, btc_amount
    )
    return {
        "current_price":  current_price,
        "market_cap_usd": market_cap_usd,
        "ent_val_usd":    ent_val_usd,
        "btc_amount":     btc_amount,
        "btc_value_usd":  btc_value_usd,
    }


def _strive_scrape_credit() -> dict:
    """Scrape Credit tab for debt and preferred."""
    soup = _soup(STRIVE_CREDIT_URL)
    page_text = soup.get_text(separator="\n")

    debt_usd      = 0.0
    preferred_usd = 0.0

    # Pattern: "Total Debt Outstanding" near a $10.00M-style value
    m = re.search(
        r"(?i)total\s*debt\s*outstanding[^$\d]{0,40}\$?([\d,]+\.?\d*)\s*M",
        page_text
    )
    if m:
        debt_usd = float(m.group(1).replace(",", "")) * 1_000_000

    # Pattern: "Total Preferred Outstanding"
    m = re.search(
        r"(?i)total\s*preferred\s*outstanding[^$\d]{0,40}\$?([\d,]+\.?\d*)\s*M",
        page_text
    )
    if m:
        preferred_usd = float(m.group(1).replace(",", "")) * 1_000_000

    # Fallback — scan small divs
    if debt_usd == 0 or preferred_usd == 0:
        for block in soup.find_all(["div", "tr", "li"]):
            block_txt = block.get_text(separator=" ", strip=True)
            if len(block_txt) > 200:
                continue
            if debt_usd == 0 and re.search(r"total\s*debt", block_txt, re.I):
                m2 = re.search(r"\$?([\d,]+\.?\d*)\s*M", block_txt)
                if m2:
                    debt_usd = float(m2.group(1).replace(",", "")) * 1_000_000
            if preferred_usd == 0 and re.search(r"total\s*preferred", block_txt, re.I):
                m2 = re.search(r"\$?([\d,]+\.?\d*)\s*M", block_txt)
                if m2:
                    preferred_usd = float(m2.group(1).replace(",", "")) * 1_000_000

    logger.info("[ASST] Credit: debt=$%.0fM  pref=$%.0fM",
                debt_usd / 1e6, preferred_usd / 1e6)
    return {"debt_usd": debt_usd, "preferred_usd": preferred_usd}


def _strive_scrape_shares() -> dict:
    """Scrape Shares tab for fully diluted shares outstanding."""
    soup = _soup(STRIVE_SHARES_URL)
    page_text = soup.get_text(separator="\n")

    diluted_shares = 0.0

    # Look for "Assumed Diluted" pattern (same naming as Strategy)
    m = re.search(
        r"(?i)assumed\s*diluted[^0-9]{0,40}([\d,]+)\b",
        page_text
    )
    if m:
        diluted_shares = float(m.group(1).replace(",", ""))

    # Fallback: "Effective Diluted (excl. Warrants)"
    if diluted_shares == 0:
        m = re.search(
            r"(?i)effective\s*diluted[^0-9]{0,40}([\d,]+)\b",
            page_text
        )
        if m:
            diluted_shares = float(m.group(1).replace(",", ""))

    # Fallback: largest bare integer on the page that could be share count (> 50M)
    if diluted_shares == 0:
        candidates = re.findall(r"\b([\d,]{8,})\b", page_text)
        for c in candidates:
            val = float(c.replace(",", ""))
            if val > 50_000_000:
                diluted_shares = val
                break

    logger.info("[ASST] Shares: diluted=%.0f", diluted_shares)
    return {"diluted_shares": diluted_shares}


def fetch_strive() -> dict:
    """Fetch all Strive (ASST) inputs. Returns normalised dict."""
    logger.info("[ASST] Fetching home tab…")
    home = _strive_scrape_home()

    logger.info("[ASST] Fetching credit tab…")
    credit = _strive_scrape_credit()

    logger.info("[ASST] Fetching shares tab…")
    shares = _strive_scrape_shares()

    # Derive cash from EV formula
    cash = _derive_cash_from_ev(
        market_cap_usd=home["market_cap_usd"],
        debt_usd=credit["debt_usd"],
        preferred_usd=credit["preferred_usd"],
        ent_val_usd=home["ent_val_usd"],
    )

    return {
        "company":        "ASST",
        "ticker":         "ASST",
        "company_name":   "Strive Asset Management",
        "current_price":  home["current_price"],
        "debt_usd":       credit["debt_usd"],
        "preferred_usd":  credit["preferred_usd"],
        "market_cap_usd": home["market_cap_usd"],
        "cash_usd":       cash,
        "data_date":      datetime.now(pytz.timezone("America/New_York")).strftime(
                              "%m/%d/%Y %I:%M %p ET"
                          ),
        "diluted_shares": shares["diluted_shares"],
        "btc_amount":     home["btc_amount"],
    }


# ===========================================================================
#  Public dispatcher
# ===========================================================================

_FETCHERS = {
    "MSTR": fetch_mstr,
    "ASST": fetch_strive,
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
