"""
Telegram notification module.
Sends an alert when MSTR market price is at or below BTC-implied fair value.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str) -> bool:
    """
    Send a plain-text message via the configured Telegram bot.
    Returns True on success, False on failure.
    """
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram not configured — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        return False

    url = TELEGRAM_API.format(token=BOT_TOKEN)
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
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


def format_alert(data: dict) -> str:
    """Build the Telegram alert message from a snapshot dict."""
    def _big(n):
        if n is None:
            return "–"
        if abs(n) >= 1e9:
            return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:
            return f"${n/1e6:.2f}M"
        return f"${n:,.2f}"

    sign = "+" if data["discount_pct"] >= 0 else ""
    return (
        "🟢 <b>MSTR UNDERVALUED ALERT</b>\n"
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


def maybe_notify(data: dict) -> bool:
    """
    Send a Telegram alert only when market price ≤ implied price.
    Returns True if a message was sent.
    """
    if not data.get("is_undervalued"):
        logger.info("Signal is %s — no Telegram alert.", data.get("signal", "N/A"))
        return False

    logger.info("Signal is UNDERVALUED — sending Telegram alert…")
    message = format_alert(data)
    return send_telegram(message)
