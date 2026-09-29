"""Shop tools the workers can call.

In a real deployment these wrap your POS, email, calendar and supplier
systems. Here they read and write a small in-memory shop so the example
runs anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]
    requires_approval: bool = False

    def spec(self) -> dict[str, Any]:
        """The tool definition sent to the model."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


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


# --- Tool functions ---------------------------------------------------------

def check_inventory() -> dict:
    return SHOP["inventory"]


def list_orders(due_within_days: int = 2) -> list:
    cutoff = TODAY + timedelta(days=due_within_days)
    return [o for o in SHOP["orders"] if date.fromisoformat(o["due"]) <= cutoff]


def list_inquiries() -> list:
    return SHOP["inquiries"]


def sales_summary() -> dict:
    sales = SHOP["sales_today"]
    return {"orders": len(sales), "revenue": round(sum(sales), 2)}


def upcoming_occasions(days: int = 14) -> list:
    cutoff = TODAY + timedelta(days=days)
    return [c for c in SHOP["customers_with_occasions"] if date.fromisoformat(c["date"]) <= cutoff]


def send_quote(to: str, amount: float, summary: str, reason: str = "") -> dict:
    SHOP["sent"].append({"type": "quote", "to": to, "amount": amount, "summary": summary})
    return {"sent": True}


def place_wholesale_order(items: dict, reason: str = "") -> dict:
    SHOP["sent"].append({"type": "wholesale_order", "items": items})
    return {"placed": True}


def publish_post(text: str, reason: str = "") -> dict:
    SHOP["sent"].append({"type": "post", "text": text})
    return {"published": True}


def send_customer_email(to: str, subject: str, body: str, reason: str = "") -> dict:
    SHOP["sent"].append({"type": "email", "to": to, "subject": subject})
    return {"sent": True}


REASON = {"type": "string", "description": "One line for the owner explaining why."}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        # Read-only: run immediately.
        Tool("check_inventory", "Current stem counts, cost per stem and days of vase life left.", _schema({}), check_inventory),
        Tool("list_orders", "Orders due within N days.", _schema({"due_within_days": {"type": "integer"}}), list_orders),
        Tool("list_inquiries", "New customer inquiries from email, web and DMs.", _schema({}), list_inquiries),
        Tool("sales_summary", "Today's order count and revenue.", _schema({}), sales_summary),
        Tool("upcoming_occasions", "Repeat customers with an occasion coming up.", _schema({"days": {"type": "integer"}}), upcoming_occasions),
        # Commits money, customers or the brand: queued for the owner.
        Tool(
            "send_quote",
            "Send a price quote to a customer.",
            _schema({"to": {"type": "string"}, "amount": {"type": "number"}, "summary": {"type": "string"}, "reason": REASON}, ["to", "amount", "summary"]),
            send_quote,
            requires_approval=True,
        ),
        Tool(
            "place_wholesale_order",
            "Order stems from the wholesaler. items maps stem name to count.",
            _schema({"items": {"type": "object", "additionalProperties": {"type": "integer"}}, "reason": REASON}, ["items"]),
            place_wholesale_order,
            requires_approval=True,
        ),
        Tool(
            "publish_post",
            "Publish a social media post for the shop.",
            _schema({"text": {"type": "string"}, "reason": REASON}, ["text"]),
            publish_post,
            requires_approval=True,
        ),
        Tool(
            "send_customer_email",
            "Email a customer (reminders, follow-ups).",
            _schema({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "reason": REASON}, ["to", "subject", "body"]),
            send_customer_email,
            requires_approval=True,
        ),
    ]
}
