"""The agent loop: send a task to Claude, run the tools it asks for, repeat.

Tools come from an MCP server. The loop lists them, hands Claude the ones
this worker is allowed to use, and calls them back through the MCP client.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import Client
from mcp import types

from .approval import ApprovalGate
from .workers import Worker

MODEL = os.environ.get("SHOP_AGENTS_MODEL", "claude-sonnet-5-5")
MAX_TURNS = 8


def to_claude_tool(tool: types.Tool) -> dict[str, Any]:
    """An MCP tool definition, in the shape the Messages API expects."""
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


async def call_mcp_tool(shop: Client, name: str, args: dict[str, Any]) -> str:
    """Call a tool on the MCP server and return its result as text for Claude."""
    result = await shop.call_tool(name, args, raise_on_error=False)
    text = "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))
    if result.is_error:
        raise RuntimeError(text or f"Tool {name} failed.")
    return text


async def run_worker(client: Any, shop: Client, worker: Worker, task: str, gate: ApprovalGate) -> str:
    """Run one worker on one task and return its final report."""
    tools = [to_claude_tool(t) for t in await shop.list_tools() if t.name in worker.tools]
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]

    for _ in range(MAX_TURNS):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=worker.system_prompt,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name not in worker.tools:
                # A worker may only use the tools it was given, whatever the server offers.
                content, is_error = f"Tool {block.name} is not available to this worker.", True
            else:
                try:
                    content = await gate.submit(
                        worker=worker.name,
                        tool=block.name,
                        args=block.input,
                        run=lambda n=block.name, a=block.input: call_mcp_tool(shop, n, a),
                    )
                    is_error = False
                except RuntimeError as e:
                    content, is_error = str(e), True
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
            )
        messages.append({"role": "user", "content": results})

    return f"[{worker.name}] stopped after {MAX_TURNS} turns without finishing."
