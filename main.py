"""Run the flower shop agents from the command line.

    python main.py                 # morning brief
    python main.py "Quote the June wedding inquiry"

The agents get their tools from the shop's MCP server. By default that
server runs in this process. Set SHOP_AGENTS_MCP to a server URL or script
path to use another one.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import anthropic
from fastmcp import Client

from shop_agents import tools
from shop_agents.approval import ApprovalGate
from shop_agents.coordinator import MORNING_BRIEF, run_coordinator
from shop_agents.runner import call_mcp_tool

AUDIT_FILE = Path("audit.jsonl")


def audit(event: dict) -> None:
    with AUDIT_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


async def review_approvals(gate: ApprovalGate, shop: Client) -> None:
    for action in gate.open_items():
        print(f"\n[{action.id}] {action.worker} wants to {action.tool}")
        print(f"    why: {action.reason or '(no reason given)'}")
        print(f"    args: {json.dumps(action.args, indent=2)}")
        choice = input("    approve? [y/N] ").strip().lower()
        await gate.decide(action.id, approve=choice == "y", run=lambda a: call_mcp_tool(shop, a.tool, a.args))


async def main() -> None:
    request = " ".join(sys.argv[1:]) or MORNING_BRIEF
    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY
    gate = ApprovalGate(audit_log=audit)

    async with Client(os.environ.get("SHOP_AGENTS_MCP") or tools.mcp) as shop:
        print(await run_coordinator(client, shop, request, gate))

        if gate.open_items():
            print("\n--- Waiting for your approval ---")
            await review_approvals(gate, shop)
            approved = sum(a.status == "approved" for a in gate.pending.values())
            print(f"\nActions carried out: {approved}. Full log in {AUDIT_FILE}.")


if __name__ == "__main__":
    asyncio.run(main())
