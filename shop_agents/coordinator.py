"""The coordinator: the one agent the owner talks to.

It never touches shop systems directly. Its only tools are the workers,
so every real action still flows through a narrow worker and the
approval gate.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from .approval import ApprovalGate
from .runner import MAX_TURNS, MODEL, run_worker
from .workers import WORKERS

COORDINATOR_PROMPT = """
You coordinate a small team of worker agents for a flower shop owner.
Break the owner's request into tasks, delegate each one to the right
worker, and combine their reports into one short answer.

Lead with what needs the owner's decision today. Then list what is
waiting for approval, then anything informational. Be brief and concrete.
""".strip()

MORNING_BRIEF = (
    "Prepare my morning brief: orders due soon and new inquiries, stems that "
    "need to sell first and whether we need a wholesale order, any customer "
    "occasions coming up, and yesterday's sales picture."
)


def _delegate_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": f"delegate_to_{name}",
            "description": f"Send a task to the {name} worker. {w.job}",
            "input_schema": {
                "type": "object",
                "properties": {"task": {"type": "string", "description": "A clear, self-contained task."}},
                "required": ["task"],
            },
        }
        for name, w in WORKERS.items()
    ]


async def run_coordinator(client: Any, shop: Client, request: str, gate: ApprovalGate) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": request}]
    tools = _delegate_tools()

    for _ in range(MAX_TURNS):
        response = await client.messages.create(
            model=MODEL, max_tokens=2000, system=COORDINATOR_PROMPT, tools=tools, messages=messages
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            worker = WORKERS[block.name.removeprefix("delegate_to_")]
            report = await run_worker(client, shop, worker, block.input["task"], gate)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": report})
        messages.append({"role": "user", "content": results})

    return "Coordinator stopped before finishing."
