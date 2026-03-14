"""
Telegram notification module.
Sends an alert when a company's market price is at or below BTC-implied fair value.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Remove static global fetching of secrets to fix K3s APScheduler issues
# They will be fetched dynamically inside the functions instead

# Company display names for Telegram messages
_COMPANY_LABELS = {
    "MSTR": "Strategy (MicroStrategy)",
    "ASST": "Strive Asset Management",
}


def send_telegram(message: str) -> bool:
    """Send a plain-text / HTML message. Returns True on success."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram not configured — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        return False

    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id":  chat_id,
        "text":     message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram alert sent successfully.")
        return True
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)
        return False


def format_alert(data: dict, company: str = "MSTR") -> str:
    """Build the Telegram HTML alert message."""
    def _big(n: float | None) -> str:
        if n is None:
            return "–"
        if abs(n) >= 1e9:
            return f"${n / 1e9:.2f}B"
        if abs(n) >= 1e6:
            return f"${n / 1e6:.2f}M"
        return f"${n:,.2f}"

    sign         = "+" if data["discount_pct"] >= 0 else ""
    company_name = _COMPANY_LABELS.get(company.upper(), company)

    return (
        f"🟢 <b>{company_name} ({company.upper()}) — UNDERVALUED ALERT</b>\n"
        "\n"
        f"📊 <b>Market Price :</b>  <code>${data['current_price']:.2f}</code>\n"
        f"⭐ <b>Implied Value :</b>  <code>${data['implied_price']:.2f}</code>\n"
        f"📉 <b>Discount      :</b>  <code>{sign}{data['discount_pct']:.1f}%</code>\n"
        "\n"
        f"₿ <b>BTC Price     :</b>  <code>${data['btc_price']:,.0f}</code>\n"
        f"₿ <b>BTC Holdings  :</b>  <code>{data['btc_amount']:,.0f} BTC</code>\n"
        f"💰 <b>BTC Value     :</b>  <code>{_big(data.get('btc_value_usd'))}</code>\n"
        "\n"
        f"🏦 <b>Debt          :</b>  <code>{_big(data.get('debt_usd'))}</code>\n"
        f"🏦 <b>Preferred     :</b>  <code>{_big(data.get('preferred_usd'))}</code>\n"
        f"💵 <b>Cash Reserve  :</b>  <code>{_big(data.get('cash_usd'))}</code>\n"
        "\n"
        f"🕓 <i>{data.get('data_date', '')}</i>"
    )


def maybe_notify(data: dict, company: str = "MSTR") -> bool:
    """Send alert only when market price ≤ implied price. Returns True if sent."""
    if not data.get("is_undervalued"):
        logger.info("[%s] Signal=%s — no Telegram alert.", company, data.get("signal", "N/A"))
        return False
    logger.info("[%s] Signal=UNDERVALUED — sending Telegram alert…", company)
    return send_telegram(format_alert(data, company=company))


def send_daily_report(results: dict[str, dict | None]) -> bool:
    """Send a daily summary report for all companies regardless of signal."""
    logger.info("Starting send_daily_report with %d results", len(results) if results else 0)
    
    # [DIAGNOSTIC] Log all environment keys to see what's actually available in this thread
    all_keys = sorted(list(os.environ.keys()))
    logger.info("Environment keys available: %s", ", ".join(all_keys))

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        token_found = "YES" if bot_token else "MISSING"
        chat_found = "YES" if chat_id else "MISSING"
        logger.warning(
            "Telegram not configured (in send_daily_report) — TOKEN:%s, CHAT_ID:%s", 
            token_found, chat_found
        )
        return False

    lines = ["📊 <b>Daily BTC Treasury Report</b>\n"]
    has_data = False

    for company, data in results.items():
        if not data:
            logger.debug("No data for company: %s", company)
            continue
            
        has_data = True
        sign = "+" if data["discount_pct"] > 0 else ""
        
        # Determine emoji based on signal
        if data["is_undervalued"]:
            emoji = "🟢"
        elif data["discount_pct"] < -10:
            emoji = "🔴"
        else:
            emoji = "⚖️"
            
        company_name = _COMPANY_LABELS.get(company.upper(), company.upper())
        
        lines.append(f"{emoji} <b>{company_name} ({company.upper()})</b>")
        lines.append(f"• Market: <code>${data['current_price']:.2f}</code> | Implied: <code>${data['implied_price']:.2f}</code>")
        lines.append(f"• Premium/Discount: <code>{sign}{data['discount_pct']:.1f}%</code>")
        lines.append(f"• BTC Holdings: <code>{data['btc_amount']:,.0f} BTC</code>")
        lines.append("")
        
    if not has_data:
        logger.warning("send_daily_report: No company data found in results.")
        return False
        
    message = "\n".join(lines).strip()
    logger.info("Sending daily Telegram report (message length: %d)...", len(message))
    return send_telegram(message)
