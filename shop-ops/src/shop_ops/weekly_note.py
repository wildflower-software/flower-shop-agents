"""The weekly sales note for the owner, saved as a draft text. Nothing is sent.

Code runs the interpreting-sales-trends script (all the math), a model writes the
note from its output, and code checks the note before it is saved:

  * every number in it appears in the script's output (whole-number rounding allowed)
  * placeholder data is labelled as placeholder
  * at most one question for the owner, and short enough to read on a phone

A note that fails a check goes back to the model with the reason. If it still fails,
the run fails and nothing is saved.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext

from .db import PROJECT_ROOT

SKILL_DIR = PROJECT_ROOT / "skills" / "interpreting-sales-trends"
DEFAULT_MODEL = "anthropic:claude-sonnet-5-5"
PLACEHOLDER_LINE = "Placeholder data, not evidence."
MAX_CHARS = 1000          # a few SMS segments; the owner reads this on a phone
SMALL_NUMBERS = range(0, 11)  # "4 weeks", "3 points", "2 outliers"

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "sales_trends", SKILL_DIR / "scripts" / "sales_trends.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sales_trends = _load_script().sales_trends


def skill_instructions() -> str:
    """The SKILL.md body (without front matter), with step 1 already done for the model."""
    body = re.sub(r"^---\n.*?\n---\n", "", (SKILL_DIR / "SKILL.md").read_text(), flags=re.S)
    return (
        "You write the shop's weekly sales note for the owner, who reads it as a text.\n"
        "The script in step 1 has already been run for you. Its JSON output is in the "
        "message. Copy numbers from it as given; you may round money to whole dollars "
        "and percentages to whole numbers. Reply with the note text only.\n\n" + body
    )


@dataclass
class NoteDeps:
    trends: dict


def allowed_numbers(trends: dict) -> set[float]:
    """Every number the note may use: the values in the output, and date parts."""
    found: set[float] = set(SMALL_NUMBERS)

    def walk(value):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            for v in (value, abs(value)):
                found.update({float(v), float(round(v)), round(float(v), 1)})
        elif isinstance(value, str):
            for part in re.findall(r"\d+(?:\.\d+)?", value):
                found.add(float(part))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(k)
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)

    walk(trends)
    found.add(float(len(trends.get("outliers", []))))
    return found


def numbers_not_in_data(note: str, trends: dict) -> list[str]:
    allowed = allowed_numbers(trends)
    unknown = []
    for token in _NUMBER.findall(note):
        n = float(token.replace(",", ""))
        if not any(abs(n - a) < 0.051 for a in allowed):
            unknown.append(token)
    return unknown


def check_note(note: str, trends: dict) -> list[str]:
    """Problems with a note, in words the model can act on. Empty means it passes."""
    problems = []
    if trends["data_basis"] in ("synthetic", "mixed") and not note.strip().startswith(PLACEHOLDER_LINE):
        problems.append(f'The data is {trends["data_basis"]}: start the note with "{PLACEHOLDER_LINE}"')
    if note.count("?") > 1:
        problems.append("Ask the owner at most one question.")
    if len(note) > MAX_CHARS:
        problems.append(f"Keep it under {MAX_CHARS} characters; it is {len(note)}.")
    unknown = numbers_not_in_data(note, trends)
    if unknown:
        problems.append("These numbers are not in the script output; use only numbers from it: "
                        + ", ".join(unknown))
    return problems


def build_agent(model=None, durable: bool = False) -> Agent[NoteDeps, str]:
    """The note writer. It has no tools: it can only return text, which code checks.

    durable=True runs each model call as a Prefect task (with retries) when the
    agent is run inside a Prefect flow.
    """
    capabilities = []
    if durable:
        from pydantic_ai.durable_exec.prefect import PrefectDurability, TaskConfig
        capabilities.append(PrefectDurability(
            model_task_config=TaskConfig(retries=3, retry_delay_seconds=[10, 30, 90], timeout_seconds=120)))
    agent = Agent(
        model or os.environ.get("SHOP_OPS_MODEL", DEFAULT_MODEL),
        deps_type=NoteDeps,
        output_type=str,
        instructions=skill_instructions(),
        retries=2,
        defer_model_check=True,
        name="weekly-sales-note",
        capabilities=capabilities,
    )

    @agent.output_validator
    def _checked(ctx: RunContext[NoteDeps], note: str) -> str:
        problems = check_note(note, ctx.deps.trends)
        if problems:
            raise ModelRetry(" ".join(problems))
        return note.strip()

    return agent


def no_sales_note(trends: dict) -> str:
    p = trends["period"]
    return f"Sales, {p['start']} to {p['end']}: no sales recorded for this period."


def write_note(trends: dict, agent: Agent[NoteDeps, str] | None = None) -> str:
    if trends["data_basis"] == "none":
        return no_sales_note(trends)  # nothing to interpret; no model call
    agent = agent or build_agent()
    prompt = "Script output:\n```json\n" + json.dumps(trends, indent=2) + "\n```"
    return agent.run_sync(prompt, deps=NoteDeps(trends)).output


def save_draft(conn: sqlite3.Connection, body: str) -> int:
    """Save the note for the owner's review. Status 'draft': nothing has been sent."""
    cur = conn.execute(
        "INSERT INTO recommendation_message(run_at, channel, body, status) VALUES (?, 'sms', ?, 'draft')",
        (datetime.now().isoformat(sep=" ", timespec="seconds"), body))
    conn.commit()
    return cur.lastrowid


def last_sales_day(conn: sqlite3.Connection) -> date | None:
    day = conn.execute("SELECT MAX(day) FROM daily_sales").fetchone()[0]
    return date.fromisoformat(day) if day else None


def db_path_from_env(default: Path) -> Path:
    return Path(os.environ.get("SHOP_OPS_DB", default))
