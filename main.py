"""Run the flower shop agents from the command line.

    uv run python main.py                 # morning brief
    uv run python main.py "Quote the June wedding inquiry"

The agents are PydanticAI agents, run inside a Prefect flow. They get their tools
from the shop's MCP server, which runs in this process by default. Set
SHOP_AGENTS_MCP to a server URL or script path to use another one.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client

from shop_agents.approval import ApprovalGate
from shop_agents.coordinator import MORNING_BRIEF
from shop_agents.flows import handle_request
from shop_agents.runner import call_mcp_tool, shop_server

AUDIT_FILE = Path("audit.jsonl")


def audit(event: dict) -> None:
    with AUDIT_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


async def review_approvals(gate: ApprovalGate) -> None:
    async with Client(shop_server()) as shop:
        for action in gate.open_items():
            print(f"\n[{action.id}] {action.worker} wants to {action.tool}")
            print(f"    why: {action.reason or '(no reason given)'}")
            print(f"    args: {json.dumps(action.args, indent=2)}")
            choice = input("    approve? [y/N] ").strip().lower()
            await gate.decide(action.id, approve=choice == "y",
                              run=lambda a: call_mcp_tool(shop, a.tool, a.args))


async def main() -> None:
    request = " ".join(sys.argv[1:]) or MORNING_BRIEF
    gate = ApprovalGate(audit_log=audit)
    print(await handle_request(request, gate))  # reads ANTHROPIC_API_KEY

    if gate.open_items():
        print("\n--- Waiting for your approval ---")
        await review_approvals(gate)
        approved = sum(a.status == "approved" for a in gate.pending.values())
        print(f"\nActions carried out: {approved}. Full log in {AUDIT_FILE}.")


if __name__ == "__main__":
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    asyncio.run(main())
