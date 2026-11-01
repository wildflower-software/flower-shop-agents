"""The weekly sales note: checks in code, a scripted fake model, and a draft that is never sent."""

from datetime import date

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from shop_ops import synthetic, weekly_note
from shop_ops.weekly_note import PLACEHOLDER_LINE, build_agent, check_note, save_draft, write_note


@pytest.fixture
def trends(conn):
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 2, 28))
    return weekly_note.sales_trends(conn, as_of=date(2026, 2, 20), weeks=4)


def good_note(t: dict) -> str:
    p, c = t["period"], t["change_pct"]
    o = t["outliers"][0]
    return (f"{PLACEHOLDER_LINE}\n"
            f"Sales, {p['start']} to {p['end']} (synthetic)\n"
            f"Revenue {c['revenue_vs_prior']:+}% vs the 4 weeks before.\n"
            f"Outliers:\n- {o['day']}: {o['times_usual']}x a usual {o['weekday']}.")


def scripted(*replies: str):
    """A fake model that gives these replies in order, and records what it was told."""
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        return ModelResponse(parts=[TextPart(replies[min(len(seen), len(replies)) - 1])])

    return FunctionModel(respond), seen


def test_a_note_built_from_the_output_passes(trends):
    assert check_note(good_note(trends), trends) == []


def test_invented_numbers_are_caught(trends):
    problems = check_note(good_note(trends) + "\nRain cut Tuesday by 8123.7%.", trends)
    assert any("8123.7" in p for p in problems)


def test_placeholder_data_must_be_labelled(trends):
    note = good_note(trends).replace(PLACEHOLDER_LINE + "\n", "")
    assert any(PLACEHOLDER_LINE in p for p in check_note(note, trends))


def test_at_most_one_question(trends):
    assert check_note(good_note(trends) + " Why? And why?", trends)


def test_a_bad_note_goes_back_to_the_model_with_the_reason(trends):
    model, seen = scripted(good_note(trends) + " Up 8123.7% on rain.", good_note(trends))
    note = write_note(trends, build_agent(model))
    assert note == good_note(trends)
    feedback = str(seen[1][-1].parts[-1].content)  # what the model was told on the second try
    assert "8123.7" in feedback and "not in the script output" in feedback


def test_a_note_that_keeps_failing_is_not_returned(trends):
    model, _ = scripted("Sales were up 8123.7%.")
    with pytest.raises(UnexpectedModelBehavior):
        write_note(trends, build_agent(model))


def test_no_sales_means_no_model_call(conn):
    trends = weekly_note.sales_trends(conn, as_of=date(2026, 2, 20), weeks=4)
    model, seen = scripted("should not be used")
    assert "no sales recorded" in write_note(trends, build_agent(model))
    assert seen == []


def test_the_note_is_saved_as_a_draft(conn):
    msg_id = save_draft(conn, "hello")
    row = conn.execute("SELECT channel, status, body FROM recommendation_message WHERE id = ?",
                       (msg_id,)).fetchone()
    assert row == ("sms", "draft", "hello")


def test_the_flow_saves_one_draft_and_sends_nothing(tmp_path, monkeypatch):
    """The whole Prefect flow on a file database, with the fake model as the agent's own model."""
    from prefect.testing.utilities import prefect_test_harness

    from shop_ops import flows
    from shop_ops.config import load_config
    from shop_ops.db import connect, init_schema

    db = tmp_path / "shop.db"
    conn = connect(db)
    init_schema(conn)
    load_config(conn)
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 2, 28))
    t = weekly_note.sales_trends(conn, as_of=date(2026, 2, 20), weeks=4)
    conn.close()

    fake, seen = scripted(good_note(t))
    real_build = weekly_note.build_agent
    monkeypatch.setattr(weekly_note, "build_agent",
                        lambda model=None, durable=False: real_build(fake, durable=durable))

    with prefect_test_harness():
        msg_id = flows.weekly_sales_note(weeks=4, as_of="2026-02-20", db=str(db))

    conn = connect(db)
    rows = conn.execute("SELECT id, status, body FROM recommendation_message").fetchall()
    assert rows == [(msg_id, "draft", good_note(t))]
    assert len(seen) == 1
