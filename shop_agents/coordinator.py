"""The coordinator: the one agent the owner talks to.

It never touches shop systems directly. Its only tools are the workers,
so every real action still flows through a narrow worker and the
approval gate.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import FunctionToolset

from .approval import ApprovalGate
from .runner import LIMITS, MODEL, ShopDeps, durability, worker_agent
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


def _delegate_to(agent: Agent[ShopDeps, str]):
    async def delegate(ctx: RunContext[ShopDeps], task: str) -> str:
        """The worker shares the run's approval gate and usage limits."""
        result = await agent.run(task, deps=ctx.deps, usage=ctx.usage, usage_limits=LIMITS)
        return result.output

    return delegate


def coordinator_agent(*, model: Any = None, worker_model: Any = None, server: Any = None,
                      durable: bool = False) -> Agent[ShopDeps, str]:
    """The coordinator, with one delegate_to_<worker> tool per worker."""
    delegates = FunctionToolset[ShopDeps](id="delegates")

    for name, worker in WORKERS.items():
        agent = worker_agent(worker, model=worker_model or model, server=server, durable=durable)
        delegates.add_function(
            _delegate_to(agent),
            name=f"delegate_to_{name}",
            description=f"Send a clear, self-contained task to the {name} worker. {worker.job}",
        )

    return Agent(
        model or MODEL,
        name="coordinator",
        deps_type=ShopDeps,
        output_type=str,
        instructions=COORDINATOR_PROMPT,
        # The worker's own model and tool calls are the durable steps, so the
        # delegate call itself is not wrapped in a Prefect task.
        toolsets=[delegates.with_metadata(prefect=False)],
        capabilities=durability() if durable else [],
        defer_model_check=True,
    )


async def run_coordinator(request: str, gate: ApprovalGate, **agent_options: Any) -> str:
    result = await coordinator_agent(**agent_options).run(request, deps=ShopDeps(gate))
    return result.output
