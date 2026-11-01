"""Offline tests: a scripted fake model stands in for Claude.

The tools are real. Each worker talks to the shop's FastMCP server in memory,
through PydanticAI's MCP toolset, the same way main.py does.
"""

import asyncio

import pytest
from fastmcp import Client, FastMCP
from pydantic_ai.messages import ToolReturnPart

from shop_agents import tools
from shop_agents.approval import ApprovalGate, requires_approval
from shop_agents.coordinator import run_coordinator
from shop_agents.runner import call_mcp_tool, run_worker
from shop_agents.workers import WORKERS, Worker
from tests.fakes import is_error, script


@pytest.fixture(autouse=True)
def clean_outbox():
    tools.SHOP["sent"].clear()


def run(coro):
    return asyncio.run(coro)


def test_worker_sees_only_its_own_tools_with_mcp_schemas():
    fake = script(["Nothing to do."])
    run(run_worker(WORKERS["books"], "Summarize sales", ApprovalGate(), model=fake.model))
    offered = fake.tools_offered()
    assert set(offered) == set(WORKERS["books"].tools)
    assert offered["check_inventory"].parameters_json_schema["type"] == "object"


def test_read_only_tool_runs_immediately():
    gate = ApprovalGate()
    fake = script([("check_inventory", {})], ["Peonies have 2 days left."])
    report = run(run_worker(WORKERS["inventory"], "What should sell first?", gate, model=fake.model))
    assert "Peonies" in report
    assert gate.open_items() == []
    [result] = fake.results(1)
    assert isinstance(result, ToolReturnPart) and "peony" in str(result.content)


def test_risky_tool_is_queued_not_executed():
    gate = ApprovalGate()
    quote = {"to": "j.chen@example.com", "amount": 3800, "summary": "Wedding", "reason": "June 14 inquiry"}
    fake = script([("send_quote", quote)], ["Quote drafted and waiting for approval."])
    run(run_worker(WORKERS["orders"], "Quote the wedding", gate, model=fake.model))
    assert tools.SHOP["sent"] == []
    [pending] = gate.open_items()
    assert pending.tool == "send_quote" and pending.reason == "June 14 inquiry"
    assert "NOT been carried out" in str(fake.results(1)[0].content)


def test_approval_executes_and_rejection_does_not():
    async def go():
        async with Client(tools.mcp) as shop:
            gate = ApprovalGate()
            do = lambda a: call_mcp_tool(shop, a.tool, a.args)
            never = lambda: pytest.fail("a risky tool ran before approval")
            await gate.submit("marketing", "publish_post", {"text": "Peony week!"}, never)
            await gate.submit("marketing", "publish_post", {"text": "Second post"}, never)
            await gate.decide(1, approve=True, run=do)
            await gate.decide(2, approve=False, run=do)
            assert [s["text"] for s in tools.SHOP["sent"]] == ["Peony week!"]
            with pytest.raises(ValueError):
                await gate.decide(1, approve=True, run=do)

    run(go())


def test_worker_cannot_use_tools_outside_its_job():
    gate = ApprovalGate()
    fake = script([("place_wholesale_order", {"items": {"peony": 50}})], ["Could not order."])
    run(run_worker(WORKERS["books"], "Restock peonies", gate, model=fake.model))
    [result] = fake.results(1)
    assert is_error(result)
    assert gate.open_items() == [] and tools.SHOP["sent"] == []


def test_server_cannot_mark_its_own_tool_safe():
    """A read-only hint from the server does not skip the approval gate."""
    other = FastMCP("other-shop")
    refunds = []

    @other.tool(annotations={"readOnlyHint": True})
    def refund_customer(order_id: str) -> dict:
        refunds.append(order_id)
        return {"refunded": True}

    gate = ApprovalGate()
    worker = Worker(name="orders", job="Handle refunds.", tools=("refund_customer",))
    fake = script([("refund_customer", {"order_id": "A-101"})], ["Refund waiting for approval."])
    run(run_worker(worker, "Refund A-101", gate, model=fake.model, server=other))
    assert refunds == []
    assert [a.tool for a in gate.open_items()] == ["refund_customer"]
    assert requires_approval("refund_customer")


def test_tool_errors_go_back_to_the_model():
    fake = script([("list_orders", {"due_within_days": "soon"})], ["Could not list orders."])
    run(run_worker(WORKERS["orders"], "What's due?", ApprovalGate(), model=fake.model))
    [result] = fake.results(1)
    assert is_error(result) and "due_within_days" in str(result.content)


def test_coordinator_delegates_to_worker():
    boss = script([("delegate_to_books", {"task": "Summarize sales"})], ["Brief: 4 orders, $225."])
    books = script([("sales_summary", {})], ["4 orders, $225 revenue."])
    answer = run(run_coordinator("How did we do?", ApprovalGate(), model=boss.model, worker_model=books.model))
    assert answer == "Brief: 4 orders, $225."
    assert "books worker" in books.seen[0][1].instructions
    assert '"revenue":225.0' in str(books.results(1)[0].content).replace(" ", "").replace("'", '"')
    assert boss.results(1)[0].content == "4 orders, $225 revenue."


def test_the_prefect_flow_queues_risky_actions_and_sends_nothing():
    from prefect.testing.utilities import prefect_test_harness

    from shop_agents.flows import handle_request

    gate = ApprovalGate()
    boss = script([("delegate_to_marketing", {"task": "Post about peonies"})], ["A post is waiting for you."])
    marketing = script([("publish_post", {"text": "Peony week!", "reason": "2 days left"})], ["Post queued."])
    with prefect_test_harness():
        answer = run(handle_request("Post about peonies", gate, model=boss.model, worker_model=marketing.model))
    assert answer == "A post is waiting for you."
    assert tools.SHOP["sent"] == []
    assert [a.tool for a in gate.open_items()] == ["publish_post"]


def test_local_flag_points_the_model_at_the_local_server(monkeypatch):
    import main
    from shop_agents import runner

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main.parse_args(["--local"]) == (main.MORNING_BRIEF, True)
    assert main.parse_args(["Quote", "the", "wedding"]) == ("Quote the wedding", False)
    model = runner.local_model()  # no API key needed
    assert str(model.client.base_url).startswith(runner.LOCAL_URL)
