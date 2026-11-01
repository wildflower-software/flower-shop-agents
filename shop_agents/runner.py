"""Worker agents, built with PydanticAI.

Each worker is a PydanticAI agent whose tools come from the shop's MCP server.
Two layers sit between the model and the server, both in code:

1. The allow-list: the worker sees only the tools in its job (workers.py).
2. The approval gate: a risky call is queued for the owner and never reaches the
   server. The model is told plainly that nothing has happened yet (approval.py).

PydanticAI runs the loop: send the task, run the tools the model asks for, repeat.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from mcp import types
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool, WrapperToolset
from pydantic_ai.usage import UsageLimits

from . import tools
from .approval import ApprovalGate
from .workers import Worker

MODEL = os.environ.get("SHOP_AGENTS_MODEL", "anthropic:claude-sonnet-5-5")
LOCAL_URL = os.environ.get("SHOP_AGENTS_LOCAL_URL", "http://127.0.0.1:8080")
MAX_TURNS = 8
LIMITS = UsageLimits(request_limit=MAX_TURNS)


def local_model() -> Any:
    """A model on a local server that speaks the Anthropic Messages API, e.g. llama.cpp's llama-server.

    The server runs whichever model it loaded, so the model name here is only a label.
    No API key is needed; the placeholder keeps the client from looking for one.
    """
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel("local", provider=AnthropicProvider(base_url=LOCAL_URL, api_key="local"))


@dataclass
class ShopDeps:
    """What every agent in a run shares: the one approval gate."""

    gate: ApprovalGate


def shop_server() -> Any:
    """The shop's MCP server: in this process by default, or SHOP_AGENTS_MCP (a URL or script path)."""
    return os.environ.get("SHOP_AGENTS_MCP") or tools.mcp


@dataclass
class GatedToolset(WrapperToolset[ShopDeps]):
    """Sends every tool call through the approval gate before it can reach the server."""

    worker: str = ""

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext[ShopDeps],
                        tool: ToolsetTool[ShopDeps]) -> Any:
        return await ctx.deps.gate.submit(
            worker=self.worker,
            tool=name,
            args=tool_args,
            run=lambda: self.wrapped.call_tool(name, tool_args, ctx, tool),
        )



def durability() -> list:
    """Run each model call and MCP call as a Prefect task, with retries, when inside a Prefect flow."""
    from pydantic_ai.durable_exec.prefect import PrefectDurability, TaskConfig

    return [PrefectDurability(model_task_config=TaskConfig(retries=3, retry_delay_seconds=[5, 20, 60]))]


def worker_agent(worker: Worker, *, model: Any = None, server: Any = None,
                 durable: bool = False) -> Agent[ShopDeps, str]:
    allowed = set(worker.tools)
    shop = MCPToolset(server or shop_server(), id=f"{worker.name}-shop")
    toolsets: list[AbstractToolset[ShopDeps]] = [
        GatedToolset(shop.filtered(lambda ctx, tool_def: tool_def.name in allowed), worker=worker.name)
    ]
    return Agent(
        model or MODEL,
        name=f"{worker.name}-worker",
        deps_type=ShopDeps,
        output_type=str,
        instructions=worker.system_prompt,
        toolsets=toolsets,
        capabilities=durability() if durable else [],
        defer_model_check=True,
    )


async def run_worker(worker: Worker, task: str, gate: ApprovalGate, *, model: Any = None,
                     server: Any = None) -> str:
    """Run one worker on one task and return its final report."""
    result = await worker_agent(worker, model=model, server=server).run(
        task, deps=ShopDeps(gate), usage_limits=LIMITS)
    return result.output


async def call_mcp_tool(shop: Client, name: str, args: dict[str, Any]) -> str:
    """Call a tool on the MCP server directly. Used to carry out an action after the owner approves it."""
    result = await shop.call_tool(name, args, raise_on_error=False)
    text = "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))
    if result.is_error:
        raise RuntimeError(text or f"Tool {name} failed.")
    return text
