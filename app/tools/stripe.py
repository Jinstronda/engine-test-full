"""Stripe tools — payments, customers, invoices, and subscriptions.

Docs: https://stripe.com/docs/api
All calls use the Stripe secret key via HTTP Basic auth (no SDK required).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from langchain_core.tools import tool

from app.tools import register

# ── Configuration ──────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = "PLACEHOLDER_STRIPE_SECRET_KEY"
STRIPE_PUBLISHABLE_KEY = "PLACEHOLDER_STRIPE_PUBLISHABLE_KEY"
# ───────────────────────────────────────────────────────────────────────────────

_BASE = "https://api.stripe.com/v1"


def _stripe_request(method: str, path: str, params: dict | None = None) -> dict:
    """Low-level helper: send a request to the Stripe API and return parsed JSON."""
    url = f"{_BASE}{path}"
    data: bytes | None = None

    if params:
        encoded = urllib.parse.urlencode(params).encode()
        if method in ("POST", "PUT", "PATCH"):
            data = encoded
        else:
            url = f"{url}?{urllib.parse.urlencode(params)}"

    credentials = base64.b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        error_body = json.loads(exc.read().decode())
        raise RuntimeError(
            f"Stripe {exc.code}: {error_body.get('error', {}).get('message', exc.reason)}"
        ) from exc


@register
@tool
def stripe_create_payment_intent(amount: int, currency: str = "usd", description: str = "") -> str:
    """Create a Stripe PaymentIntent.

    Args:
        amount: Amount in the smallest currency unit (e.g. cents for USD).
        currency: Three-letter ISO currency code, lowercase (default: "usd").
        description: Optional description for the payment.

    Returns:
        PaymentIntent ID and client_secret, or an error message.
    """
    try:
        params: dict = {"amount": amount, "currency": currency}
        if description:
            params["description"] = description
        result = _stripe_request("POST", "/payment_intents", params)
        return (
            f"PaymentIntent created. ID: {result['id']} | "
            f"Status: {result['status']} | "
            f"Client secret: {result['client_secret']}"
        )
    except Exception as exc:
        return f"Error creating PaymentIntent: {exc}"


@register
@tool
def stripe_create_customer(email: str, name: str = "", phone: str = "") -> str:
    """Create a new Stripe Customer.

    Args:
        email: Customer email address.
        name: Full name of the customer (optional).
        phone: Phone number (optional).

    Returns:
        Customer ID and email, or an error message.
    """
    try:
        params: dict = {"email": email}
        if name:
            params["name"] = name
        if phone:
            params["phone"] = phone
        result = _stripe_request("POST", "/customers", params)
        return f"Customer created. ID: {result['id']} | Email: {result['email']}"
    except Exception as exc:
        return f"Error creating customer: {exc}"


@register
@tool
def stripe_get_customer(customer_id: str) -> str:
    """Retrieve a Stripe Customer by ID.

    Args:
        customer_id: The Stripe customer ID (starts with 'cus_').

    Returns:
        Customer details (ID, email, name, balance) or an error message.
    """
    try:
        result = _stripe_request("GET", f"/customers/{customer_id}")
        return (
            f"Customer ID: {result['id']} | "
            f"Email: {result.get('email', 'N/A')} | "
            f"Name: {result.get('name', 'N/A')} | "
            f"Balance: {result.get('balance', 0)}"
        )
    except Exception as exc:
        return f"Error retrieving customer: {exc}"


@register
@tool
def stripe_list_charges(limit: int = 10, customer_id: str = "") -> str:
    """List recent Stripe charges.

    Args:
        limit: Number of charges to return (1–100, default 10).
        customer_id: Filter by customer ID (optional).

    Returns:
        A formatted list of charges with ID, amount, status, and description.
    """
    try:
        params: dict = {"limit": min(max(limit, 1), 100)}
        if customer_id:
            params["customer"] = customer_id
        result = _stripe_request("GET", "/charges", params)
        charges = result.get("data", [])
        if not charges:
            return "No charges found."
        lines = []
        for c in charges:
            lines.append(
                f"- {c['id']}: {c['amount']} {c['currency'].upper()} | "
                f"Status: {c['status']} | {c.get('description', 'no description')}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing charges: {exc}"


@register
@tool
def stripe_create_invoice(customer_id: str, description: str = "", auto_advance: bool = True) -> str:
    """Create a Stripe Invoice for a customer.

    Args:
        customer_id: The Stripe customer ID (starts with 'cus_').
        description: Optional memo / description for the invoice.
        auto_advance: If True, automatically finalise and send the invoice (default True).

    Returns:
        Invoice ID, status, and hosted URL, or an error message.
    """
    try:
        params: dict = {
            "customer": customer_id,
            "auto_advance": str(auto_advance).lower(),
        }
        if description:
            params["description"] = description
        result = _stripe_request("POST", "/invoices", params)
        return (
            f"Invoice created. ID: {result['id']} | "
            f"Status: {result['status']} | "
            f"URL: {result.get('hosted_invoice_url', 'N/A')}"
        )
    except Exception as exc:
        return f"Error creating invoice: {exc}"


@register
@tool
def stripe_create_subscription(customer_id: str, price_id: str) -> str:
    """Create a Stripe Subscription for a customer.

    Args:
        customer_id: The Stripe customer ID (starts with 'cus_').
        price_id: The Stripe Price ID to subscribe to (starts with 'price_').

    Returns:
        Subscription ID and status, or an error message.
    """
    try:
        params = {
            "customer": customer_id,
            "items[0][price]": price_id,
        }
        result = _stripe_request("POST", "/subscriptions", params)
        return (
            f"Subscription created. ID: {result['id']} | "
            f"Status: {result['status']} | "
            f"Current period end: {result.get('current_period_end', 'N/A')}"
        )
    except Exception as exc:
        return f"Error creating subscription: {exc}"
