"""Prefect flows that run the agents.

Inside a flow, every model call and every MCP tool call is a Prefect task with its
own retries and its own line in the run history, so a failed run can be read step
by step. The approval gate is unchanged: a risky call is queued in code and never
becomes a task, because it never reaches the server.
"""

from __future__ import annotations

from typing import Any

from prefect import flow, get_run_logger

from .approval import ApprovalGate
from .coordinator import MORNING_BRIEF, coordinator_agent
from .runner import ShopDeps


@flow(name="shop-request", validate_parameters=False)
async def handle_request(request: str, gate: ApprovalGate, model: Any = None,
                         worker_model: Any = None) -> str:
    """Run the coordinator on one request. Risky actions wait in the gate for the owner."""
    log = get_run_logger()
    agent = coordinator_agent(model=model, worker_model=worker_model, durable=True)
    result = await agent.run(request, deps=ShopDeps(gate))
    log.info("Done. %d action(s) waiting for the owner. Nothing was sent.", len(gate.open_items()))
    return result.output


async def morning_brief(gate: ApprovalGate, **options: Any) -> str:
    return await handle_request(MORNING_BRIEF, gate, **options)
