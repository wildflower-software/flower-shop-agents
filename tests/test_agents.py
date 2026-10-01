"""Offline tests: a scripted fake client stands in for the API."""

from types import SimpleNamespace as NS

import pytest

from shop_agents import tools
from shop_agents.approval import ApprovalGate
from shop_agents.coordinator import run_coordinator
from shop_agents.runner import run_worker
from shop_agents.workers import WORKERS


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

    def create(self, **kwargs):
        self.calls.append(kwargs)
        stop, content = self.script.pop(0)
        return NS(stop_reason=stop, content=content)


@pytest.fixture(autouse=True)
def clean_outbox():
    tools.SHOP["sent"].clear()


def test_read_only_tool_runs_immediately():
    gate = ApprovalGate()
    client = FakeClient([
        ("tool_use", [call("check_inventory", {})]),
        ("end_turn", [text("Peonies have 2 days left.")]),
    ])
    report = run_worker(client, WORKERS["inventory"], "What should sell first?", gate)
    assert "Peonies" in report
    assert gate.open_items() == []
    tool_result = client.calls[1]["messages"][2]["content"][0]["content"]
    assert "peony" in tool_result


def test_risky_tool_is_queued_not_executed():
    gate = ApprovalGate()
    client = FakeClient([
        ("tool_use", [call("send_quote", {"to": "j.chen@example.com", "amount": 3800, "summary": "Wedding", "reason": "June 14 inquiry"})]),
        ("end_turn", [text("Quote drafted and waiting for approval.")]),
    ])
    run_worker(client, WORKERS["orders"], "Quote the wedding", gate)
    assert tools.SHOP["sent"] == []
    [pending] = gate.open_items()
    assert pending.tool == "send_quote" and pending.reason == "June 14 inquiry"


def test_approval_executes_and_rejection_does_not():
    gate = ApprovalGate()
    run = lambda a: tools.TOOLS[a.tool].fn(**a.args)
    gate.submit("marketing", "publish_post", {"text": "Peony week!"}, True, lambda: None)
    gate.submit("marketing", "publish_post", {"text": "Second post"}, True, lambda: None)
    gate.decide(1, approve=True, run=run)
    gate.decide(2, approve=False, run=run)
    assert [s["text"] for s in tools.SHOP["sent"]] == ["Peony week!"]
    with pytest.raises(ValueError):
        gate.decide(1, approve=True, run=run)


def test_worker_cannot_use_tools_outside_its_job():
    gate = ApprovalGate()
    client = FakeClient([
        ("tool_use", [call("place_wholesale_order", {"items": {"peony": 50}})]),
        ("end_turn", [text("Could not order.")]),
    ])
    run_worker(client, WORKERS["books"], "Restock peonies", gate)
    result = client.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True
    assert gate.open_items() == [] and tools.SHOP["sent"] == []


def test_coordinator_delegates_to_worker():
    gate = ApprovalGate()
    client = FakeClient([
        ("tool_use", [call("delegate_to_books", {"task": "Summarize sales"}, id="c1")]),
        ("tool_use", [call("sales_summary", {}, id="w1")]),
        ("end_turn", [text("4 orders, $225 revenue.")]),
        ("end_turn", [text("Brief: 4 orders, $225.")]),
    ])
    answer = run_coordinator(client, "How did we do?", gate)
    assert answer == "Brief: 4 orders, $225."
    assert "books worker" in client.calls[1]["system"]


def test_local_flag_points_client_at_local_server(monkeypatch):
    import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = main.make_client(local=True)
    assert str(client.base_url).startswith(main.LOCAL_URL)
