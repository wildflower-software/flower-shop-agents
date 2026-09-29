"""The agent loop: send a task to Claude, run the tools it asks for, repeat."""

from __future__ import annotations

import os
from typing import Any

from .approval import ApprovalGate
from .tools import TOOLS
from .workers import Worker

MODEL = os.environ.get("SHOP_AGENTS_MODEL", "claude-sonnet-5-5")
MAX_TURNS = 8


def run_worker(client: Any, worker: Worker, task: str, gate: ApprovalGate) -> str:
    """Run one worker on one task and return its final report."""
    tools = [TOOLS[name] for name in worker.tools]
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=worker.system_prompt,
            tools=[t.spec() for t in tools],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool = TOOLS.get(block.name)
            if tool is None or tool.name not in worker.tools:
                # A worker may only use the tools it was given.
                content, is_error = f"Tool {block.name} is not available to this worker.", True
            else:
                content = gate.submit(
                    worker=worker.name,
                    tool=tool.name,
                    args=block.input,
                    requires_approval=tool.requires_approval,
                    run=lambda t=tool, a=block.input: t.fn(**a),
                )
                is_error = False
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
            )
        messages.append({"role": "user", "content": results})

    return f"[{worker.name}] stopped after {MAX_TURNS} turns without finishing."
