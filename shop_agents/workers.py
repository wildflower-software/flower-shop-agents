"""Worker agent definitions.

Each worker is a narrow job description plus the few tools that job needs.
Narrow workers are easier to test, cheaper to run and easier to trust.
"""

from __future__ import annotations

from dataclasses import dataclass

SHARED_RULES = """
Rules for every worker:
- Use tools for facts. Never invent stock counts, prices or dates.
- Actions that send, spend or publish are queued for the owner. When a tool
  says an action is queued, report it as waiting for approval, not as done.
- Include a one-line `reason` on every action so the owner can approve quickly.
- Finish with a short report: what you found, what you queued, what needs a decision.
""".strip()


@dataclass(frozen=True)
class Worker:
    name: str
    job: str
    tools: tuple[str, ...]

    @property
    def system_prompt(self) -> str:
        return f"You are the {self.name} worker for a small flower shop.\n\n{self.job}\n\n{SHARED_RULES}"


WORKERS: dict[str, Worker] = {
    w.name: w
    for w in [
        Worker(
            name="orders",
            job=(
                "You handle incoming inquiries and upcoming orders. Draft quotes for custom "
                "work such as weddings and events, flag anything due in the next 48 hours, "
                "and check inventory before promising specific flowers."
            ),
            tools=("list_inquiries", "list_orders", "check_inventory", "send_quote"),
        ),
        Worker(
            name="inventory",
            job=(
                "You manage perishable stock. Flag stems with two days or less of vase life "
                "so they can be sold first, and draft the wholesale order based on open "
                "orders and current counts."
            ),
            tools=("check_inventory", "list_orders", "place_wholesale_order"),
        ),
        Worker(
            name="marketing",
            job=(
                "You keep customers coming back. Draft posts featuring stems that need to "
                "move, and draft reminder emails to repeat customers with occasions coming up."
            ),
            tools=("check_inventory", "upcoming_occasions", "publish_post", "send_customer_email"),
        ),
        Worker(
            name="books",
            job=(
                "You watch the numbers. Summarize today's sales, estimate the cost of stems "
                "on hand, and point out where waste is eating margin."
            ),
            tools=("sales_summary", "check_inventory"),
        ),
    ]
}
