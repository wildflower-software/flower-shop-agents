"""Human-in-the-loop approval gate.

Every tool call a worker makes passes through here. Low-risk tools run
immediately. High-risk tools (anything that spends money, commits to a
customer, or goes public) are queued for the owner instead of executed.

Which tools are low-risk is decided here, not by the MCP server. Servers
can mark a tool read-only, but the MCP spec treats those annotations as
untrusted hints. A tool that is not on this list waits for the owner,
including any tool a server adds later.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

# The only tools that run without the owner's approval.
AUTO_APPROVED = frozenset(
    {"check_inventory", "list_orders", "list_inquiries", "sales_summary", "upcoming_occasions"}
)


def requires_approval(tool: str) -> bool:
    return tool not in AUTO_APPROVED


@dataclass
class PendingAction:
    id: int
    worker: str
    tool: str
    args: dict[str, Any]
    reason: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    status: str = "pending"  # pending | approved | rejected


class ApprovalGate:
    """Decides whether a tool call runs now or waits for a human."""

    def __init__(self, audit_log: Callable[[dict], None] | None = None):
        self._ids = itertools.count(1)
        self.pending: dict[int, PendingAction] = {}
        self._audit = audit_log or (lambda event: None)

    async def submit(
        self,
        worker: str,
        tool: str,
        args: dict[str, Any],
        run: Callable[[], Awaitable[str]],
    ) -> str:
        """Run the tool now, or queue it. Returns text for the model."""
        if not requires_approval(tool):
            result = await run()
            self._audit({"event": "auto_run", "worker": worker, "tool": tool, "args": args})
            return result

        action = PendingAction(
            id=next(self._ids),
            worker=worker,
            tool=tool,
            args=args,
            reason=args.get("reason", ""),
        )
        self.pending[action.id] = action
        self._audit({"event": "queued", "id": action.id, "worker": worker, "tool": tool, "args": args})
        # Tell the model plainly that nothing has happened yet.
        return json.dumps(
            {
                "status": "queued_for_owner_approval",
                "approval_id": action.id,
                "note": "This action has NOT been carried out. Tell the owner it is waiting for approval.",
            }
        )

    async def decide(
        self, action_id: int, approve: bool, run: Callable[[PendingAction], Awaitable[Any]]
    ) -> Any:
        """Owner approves or rejects a queued action."""
        action = self.pending[action_id]
        if action.status != "pending":
            raise ValueError(f"Action {action_id} is already {action.status}")
        action.status = "approved" if approve else "rejected"
        self._audit({"event": action.status, "id": action_id, "tool": action.tool})
        return await run(action) if approve else None

    def open_items(self) -> list[PendingAction]:
        return [a for a in self.pending.values() if a.status == "pending"]
