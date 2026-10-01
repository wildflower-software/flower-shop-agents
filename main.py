"""Run the flower shop agents from the command line.

    python main.py                 # morning brief
    python main.py "Quote the June wedding inquiry"
    python main.py --local         # use a local model instead of the API
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic

from shop_agents.approval import ApprovalGate
from shop_agents.coordinator import MORNING_BRIEF, run_coordinator
from shop_agents.tools import SHOP, TOOLS

AUDIT_FILE = Path("audit.jsonl")
LOCAL_URL = os.environ.get("SHOP_AGENTS_LOCAL_URL", "http://127.0.0.1:8080")


def audit(event: dict) -> None:
    with AUDIT_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


def review_approvals(gate: ApprovalGate) -> None:
    for action in gate.open_items():
        print(f"\n[{action.id}] {action.worker} wants to {action.tool}")
        print(f"    why: {action.reason or '(no reason given)'}")
        print(f"    args: {json.dumps(action.args, indent=2)}")
        choice = input("    approve? [y/N] ").strip().lower()
        gate.decide(action.id, approve=choice == "y", run=lambda a: TOOLS[a.tool].fn(**a.args))


def make_client(local: bool) -> anthropic.Anthropic:
    if local:
        # Any server that speaks the Anthropic Messages API, e.g. llama.cpp's llama-server.
        return anthropic.Anthropic(base_url=LOCAL_URL, api_key="local")
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY


def main() -> None:
    args = sys.argv[1:]
    local = "--local" in args
    request = " ".join(a for a in args if a != "--local") or MORNING_BRIEF
    client = make_client(local)
    gate = ApprovalGate(audit_log=audit)

    print(run_coordinator(client, request, gate))

    if gate.open_items():
        print("\n--- Waiting for your approval ---")
        review_approvals(gate)
        print(f"\nActions carried out: {len(SHOP['sent'])}. Full log in {AUDIT_FILE}.")


if __name__ == "__main__":
    main()
