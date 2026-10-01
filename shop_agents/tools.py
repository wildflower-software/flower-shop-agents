"""The shop's tools, served over MCP with FastMCP.

In a real deployment these wrap your POS, email, calendar and supplier
systems. Here they read and write a small in-memory shop so the example
runs anywhere.

The agents reach these tools through an MCP client, never by importing
them. Run this file on its own to serve the same tools to any MCP client:

    python -m shop_agents.tools
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP("flower-shop")

# Hints for MCP clients. The orchestrator does not trust them for safety:
# what needs approval is decided in approval.py.
READ_ONLY = {"readOnlyHint": True}
OUTSIDE_WORLD = {"readOnlyHint": False, "openWorldHint": True}


# --- Demo shop data ---------------------------------------------------------

TODAY = date.today()

SHOP: dict[str, Any] = {
    "inventory": {
        # stem: (count, cost per stem, days of vase life left)
        "garden rose": {"count": 120, "cost": 1.80, "days_left": 3},
        "ranunculus": {"count": 60, "cost": 1.20, "days_left": 5},
        "eucalyptus": {"count": 40, "cost": 0.60, "days_left": 9},
        "peony": {"count": 18, "cost": 3.50, "days_left": 2},
        "lisianthus": {"count": 75, "cost": 1.10, "days_left": 6},
    },
    "orders": [
        {"id": "A-101", "customer": "M. Rivera", "item": "Seasonal bouquet", "due": str(TODAY), "total": 65.0},
        {"id": "A-102", "customer": "Oak & Ash Cafe", "item": "Weekly table arrangements", "due": str(TODAY + timedelta(days=1)), "total": 140.0},
    ],
    "inquiries": [
        {"from": "j.chen@example.com", "text": "Wedding on June 14, 120 guests, blush and white, about $4k budget. Can you quote?"},
        {"from": "dm:@porchlightco", "text": "Do you deliver same day to the east side?"},
    ],
    "sales_today": [65.0, 42.0, 88.0, 30.0],
    "customers_with_occasions": [
        {"name": "S. Patel", "occasion": "anniversary", "date": str(TODAY + timedelta(days=6)), "last_order": "peonies"},
    ],
    "sent": [],  # anything that actually went out, after approval
}


# --- Read-only tools --------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
def check_inventory() -> dict:
    """Current stem counts, cost per stem and days of vase life left."""
    return SHOP["inventory"]


@mcp.tool(annotations=READ_ONLY)
def list_orders(due_within_days: int = 2) -> list:
    """Orders due within N days."""
    cutoff = TODAY + timedelta(days=due_within_days)
    return [o for o in SHOP["orders"] if date.fromisoformat(o["due"]) <= cutoff]


@mcp.tool(annotations=READ_ONLY)
def list_inquiries() -> list:
    """New customer inquiries from email, web and DMs."""
    return SHOP["inquiries"]


@mcp.tool(annotations=READ_ONLY)
def sales_summary() -> dict:
    """Today's order count and revenue."""
    sales = SHOP["sales_today"]
    return {"orders": len(sales), "revenue": round(sum(sales), 2)}


@mcp.tool(annotations=READ_ONLY)
def upcoming_occasions(days: int = 14) -> list:
    """Repeat customers with an occasion coming up."""
    cutoff = TODAY + timedelta(days=days)
    return [c for c in SHOP["customers_with_occasions"] if date.fromisoformat(c["date"]) <= cutoff]


# --- Tools that commit money, customers or the brand ------------------------
# Each takes a `reason`: one line for the owner explaining why.

@mcp.tool(annotations=OUTSIDE_WORLD)
def send_quote(to: str, amount: float, summary: str, reason: str = "") -> dict:
    """Send a price quote to a customer."""
    SHOP["sent"].append({"type": "quote", "to": to, "amount": amount, "summary": summary})
    return {"sent": True}


@mcp.tool(annotations=OUTSIDE_WORLD)
def place_wholesale_order(items: dict[str, int], reason: str = "") -> dict:
    """Order stems from the wholesaler. items maps stem name to count."""
    SHOP["sent"].append({"type": "wholesale_order", "items": items})
    return {"placed": True}


@mcp.tool(annotations=OUTSIDE_WORLD)
def publish_post(text: str, reason: str = "") -> dict:
    """Publish a social media post for the shop."""
    SHOP["sent"].append({"type": "post", "text": text})
    return {"published": True}


@mcp.tool(annotations=OUTSIDE_WORLD)
def send_customer_email(to: str, subject: str, body: str, reason: str = "") -> dict:
    """Email a customer (reminders, follow-ups)."""
    SHOP["sent"].append({"type": "email", "to": to, "subject": subject})
    return {"sent": True}


if __name__ == "__main__":
    mcp.run()
