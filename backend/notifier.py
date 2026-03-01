"""
Telegram notification module.
Sends an alert when a company's market price is at or below BTC-implied fair value.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Company display names for Telegram messages
_COMPANY_LABELS = {
    "MSTR": "Strategy (MicroStrategy)",
    "ASST": "Strive Asset Management",
}


def send_telegram(message: str) -> bool:
    """Send a plain-text / HTML message. Returns True on success."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram not configured — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        return False

    url = TELEGRAM_API.format(token=BOT_TOKEN)
    payload = {
        "chat_id":  CHAT_ID,
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
    if not BOT_TOKEN or not CHAT_ID:
        return False

    lines = ["📊 <b>Daily BTC Treasury Report</b>\n"]
    has_data = False

    for company, data in results.items():
        if not data:
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
        return False
        
    message = "\n".join(lines).strip()
    logger.info("Sending daily Telegram report…")
    return send_telegram(message)
