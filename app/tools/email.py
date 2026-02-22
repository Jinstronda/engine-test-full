"""Email sending tool powered by the Resend API.

Docs: https://resend.com/docs/api-reference/emails/send-email
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from langchain_core.tools import tool

from app.tools import register

# ── Configuration ──────────────────────────────────────────────────────────────
RESEND_API_KEY = "PLACEHOLDER_RESEND_API_KEY"
RESEND_FROM = "Fabriq Agent <noreply@fabriq.eyed.to>"  # must be a verified Resend domain
# ───────────────────────────────────────────────────────────────────────────────


@register
@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send a transactional email via Resend.

    Args:
        to: Recipient email address (or comma-separated list of addresses).
        subject: Email subject line.
        body: Plain-text body of the email.

    Returns:
        A success message containing the Resend message ID, or an error description.
    """
    recipients = [addr.strip() for addr in to.split(",")]

    payload = json.dumps(
        {
            "from": RESEND_FROM,
            "to": recipients,
            "subject": subject,
            "text": body,
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return f"Email sent successfully. Message ID: {data.get('id', 'unknown')}"
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        return f"Resend API error {exc.code}: {error_body}"
    except Exception as exc:
        return f"Failed to send email: {exc}"
