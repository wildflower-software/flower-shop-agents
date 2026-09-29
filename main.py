"""Run the flower shop agents from the command line.

    python main.py                 # morning brief
    python main.py "Quote the June wedding inquiry"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic

from shop_agents.approval import ApprovalGate
from shop_agents.coordinator import MORNING_BRIEF, run_coordinator
from shop_agents.tools import SHOP, TOOLS

AUDIT_FILE = Path("audit.jsonl")


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


def main() -> None:
    request = " ".join(sys.argv[1:]) or MORNING_BRIEF
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    gate = ApprovalGate(audit_log=audit)

    print(run_coordinator(client, request, gate))

    if gate.open_items():
        print("\n--- Waiting for your approval ---")
        review_approvals(gate)
        print(f"\nActions carried out: {len(SHOP['sent'])}. Full log in {AUDIT_FILE}.")


if __name__ == "__main__":
    main()
