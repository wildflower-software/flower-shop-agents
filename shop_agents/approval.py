"""Human-in-the-loop approval gate.

Every tool call a worker makes passes through here. Low-risk tools run
immediately. High-risk tools (anything that spends money, commits to a
customer, or goes public) are queued for the owner instead of executed.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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

    def submit(
        self,
        worker: str,
        tool: str,
        args: dict[str, Any],
        requires_approval: bool,
        run: Callable[[], Any],
    ) -> str:
        """Run the tool now, or queue it. Returns text for the model."""
        if not requires_approval:
            result = run()
            self._audit({"event": "auto_run", "worker": worker, "tool": tool, "args": args})
            return json.dumps(result, default=str)

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

    def decide(self, action_id: int, approve: bool, run: Callable[[PendingAction], Any]) -> Any:
        """Owner approves or rejects a queued action."""
        action = self.pending[action_id]
        if action.status != "pending":
            raise ValueError(f"Action {action_id} is already {action.status}")
        action.status = "approved" if approve else "rejected"
        self._audit({"event": action.status, "id": action_id, "tool": action.tool})
        return run(action) if approve else None

    def open_items(self) -> list[PendingAction]:
        return [a for a in self.pending.values() if a.status == "pending"]
