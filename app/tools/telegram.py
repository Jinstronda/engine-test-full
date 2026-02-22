"""Telegram message sending tool via the Bot API.

Set up:
1. Talk to @BotFather on Telegram → /newbot → copy the token below.
2. Start a chat with your bot (or add it to a group) once so it can message you.
3. Find your chat ID: https://api.telegram.org/bot<TOKEN>/getUpdates
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from langchain_core.tools import tool

from app.tools import register

# ── Configuration ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "PLACEHOLDER_TELEGRAM_BOT_TOKEN"  # e.g. "123456:ABC-DEF..."
TELEGRAM_DEFAULT_CHAT_ID = "8422507980"  # e.g. "987654321"
# ───────────────────────────────────────────────────────────────────────────────

_BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


@register
@tool
def send_telegram_message(message: str, chat_id: str = "") -> str:
    """Send a Telegram message via the Bot API.

    Args:
        message: The text to send (supports Markdown).
        chat_id: Telegram chat / user ID to send the message to.
                 Defaults to TELEGRAM_DEFAULT_CHAT_ID if omitted.

    Returns:
        A success message with the Telegram message ID, or an error description.
    """
    target_chat = chat_id.strip() or TELEGRAM_DEFAULT_CHAT_ID

    payload = json.dumps(
        {
            "chat_id": target_chat,
            "text": message,
            "parse_mode": "Markdown",
        }
    ).encode()

    req = urllib.request.Request(
        f"{_BASE_URL}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                msg_id = data["result"]["message_id"]
                return f"Telegram message sent. Message ID: {msg_id}"
            return f"Telegram API returned ok=false: {data}"
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        return f"Telegram API error {exc.code}: {error_body}"
    except Exception as exc:
        return f"Failed to send Telegram message: {exc}"
