"""Offline tests: a scripted fake client stands in for the API.

The tools are real. Each test talks to the shop's FastMCP server through
an in-memory MCP client, the same way main.py does.
"""

import asyncio
from types import SimpleNamespace as NS

import pytest
from fastmcp import Client, FastMCP

from shop_agents import tools
from shop_agents.approval import ApprovalGate, requires_approval
from shop_agents.coordinator import run_coordinator
from shop_agents.runner import call_mcp_tool, run_worker
from shop_agents.workers import WORKERS, Worker


def text(t):
    return NS(type="text", text=t)


def call(name, args, id="t1"):
    return NS(type="tool_use", name=name, input=args, id=id)


class FakeClient:
    """Returns scripted responses in order and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        stop, content = self.script.pop(0)
        return NS(stop_reason=stop, content=content)


def with_shop(test, server=tools.mcp):
    """Run an async test body with a connected MCP client."""

    async def go():
        async with Client(server) as shop:
            return await test(shop)

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def clean_outbox():
    tools.SHOP["sent"].clear()


def test_worker_sees_only_its_own_tools_with_mcp_schemas():
    async def test(shop):
        client = FakeClient([("end_turn", [text("Nothing to do.")])])
        await run_worker(client, shop, WORKERS["books"], "Summarize sales", ApprovalGate())
        sent = {t["name"]: t for t in client.calls[0]["tools"]}
        assert set(sent) == set(WORKERS["books"].tools)
        assert sent["check_inventory"]["input_schema"]["type"] == "object"

    with_shop(test)


def test_read_only_tool_runs_immediately():
    async def test(shop):
        gate = ApprovalGate()
        client = FakeClient([
            ("tool_use", [call("check_inventory", {})]),
            ("end_turn", [text("Peonies have 2 days left.")]),
        ])
        report = await run_worker(client, shop, WORKERS["inventory"], "What should sell first?", gate)
        assert "Peonies" in report
        assert gate.open_items() == []
        tool_result = client.calls[1]["messages"][2]["content"][0]["content"]
        assert "peony" in tool_result

    with_shop(test)


def test_risky_tool_is_queued_not_executed():
    async def test(shop):
        gate = ApprovalGate()
        client = FakeClient([
            ("tool_use", [call("send_quote", {"to": "j.chen@example.com", "amount": 3800, "summary": "Wedding", "reason": "June 14 inquiry"})]),
            ("end_turn", [text("Quote drafted and waiting for approval.")]),
        ])
        await run_worker(client, shop, WORKERS["orders"], "Quote the wedding", gate)
        assert tools.SHOP["sent"] == []
        [pending] = gate.open_items()
        assert pending.tool == "send_quote" and pending.reason == "June 14 inquiry"

    with_shop(test)


def test_approval_executes_and_rejection_does_not():
    async def test(shop):
        gate = ApprovalGate()
        run = lambda a: call_mcp_tool(shop, a.tool, a.args)
        never = lambda: pytest.fail("a risky tool ran before approval")
        await gate.submit("marketing", "publish_post", {"text": "Peony week!"}, never)
        await gate.submit("marketing", "publish_post", {"text": "Second post"}, never)
        await gate.decide(1, approve=True, run=run)
        await gate.decide(2, approve=False, run=run)
        assert [s["text"] for s in tools.SHOP["sent"]] == ["Peony week!"]
        with pytest.raises(ValueError):
            await gate.decide(1, approve=True, run=run)

    with_shop(test)


def test_worker_cannot_use_tools_outside_its_job():
    async def test(shop):
        gate = ApprovalGate()
        client = FakeClient([
            ("tool_use", [call("place_wholesale_order", {"items": {"peony": 50}})]),
            ("end_turn", [text("Could not order.")]),
        ])
        await run_worker(client, shop, WORKERS["books"], "Restock peonies", gate)
        result = client.calls[1]["messages"][2]["content"][0]
        assert result["is_error"] is True
        assert gate.open_items() == [] and tools.SHOP["sent"] == []

    with_shop(test)


def test_server_cannot_mark_its_own_tool_safe():
    """A read-only hint from the server does not skip the approval gate."""
    other = FastMCP("other-shop")
    refunds = []

    @other.tool(annotations={"readOnlyHint": True})
    def refund_customer(order_id: str) -> dict:
        refunds.append(order_id)
        return {"refunded": True}

    async def test(shop):
        gate = ApprovalGate()
        worker = Worker(name="orders", job="Handle refunds.", tools=("refund_customer",))
        client = FakeClient([
            ("tool_use", [call("refund_customer", {"order_id": "A-101"})]),
            ("end_turn", [text("Refund waiting for approval.")]),
        ])
        await run_worker(client, shop, worker, "Refund A-101", gate)
        assert refunds == []
        assert [a.tool for a in gate.open_items()] == ["refund_customer"]

    assert requires_approval("refund_customer")
    with_shop(test, server=other)


def test_tool_errors_go_back_to_the_model():
    async def test(shop):
        gate = ApprovalGate()
        client = FakeClient([
            ("tool_use", [call("list_orders", {"due_within_days": "soon"})]),
            ("end_turn", [text("Could not list orders.")]),
        ])
        await run_worker(client, shop, WORKERS["orders"], "What's due?", gate)
        result = client.calls[1]["messages"][2]["content"][0]
        assert result["is_error"] is True and "due_within_days" in result["content"]

    with_shop(test)


def test_coordinator_delegates_to_worker():
    async def test(shop):
        gate = ApprovalGate()
        client = FakeClient([
            ("tool_use", [call("delegate_to_books", {"task": "Summarize sales"}, id="c1")]),
            ("tool_use", [call("sales_summary", {}, id="w1")]),
            ("end_turn", [text("4 orders, $225 revenue.")]),
            ("end_turn", [text("Brief: 4 orders, $225.")]),
        ])
        answer = await run_coordinator(client, shop, "How did we do?", gate)
        assert answer == "Brief: 4 orders, $225."
        assert "books worker" in client.calls[1]["system"]
        assert '"revenue":225.0' in client.calls[2]["messages"][2]["content"][0]["content"]

    with_shop(test)
