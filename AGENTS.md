# AGENTS.md

Instructions for coding agents working on this repository. People should
start with [README.md](README.md).

## Setup and checks

- Python is managed by `uv` and pinned in `.python-version`. Use the `.venv`
  environment: `uv venv`, then `uv pip install -r requirements.txt`.
- Run the tests with `uv run pytest`. They are offline and need no API key.
  Run them after every change.

## Layout

- `shop_agents/tools.py`: the shop's tools, served by a FastMCP server.
- `shop_agents/workers.py`: each worker's job and tool allow-list.
- `shop_agents/approval.py`: the approval gate and the audit trail.
- `shop_agents/runner.py` and `coordinator.py`: the agents, built with
  PydanticAI. `runner.py` holds the allow-list filter and `GatedToolset`.
- `shop_agents/flows.py`: the Prefect flow that runs a request.

## Rules that must not change by accident

- **Approval is enforced in code.** Only tools listed in `AUTO_APPROVED` in
  `approval.py` run without the owner. Don't add a tool to that list unless
  it only reads data, and add a test that shows it.
- **The allow-list lives in `workers.py`.** An MCP server's tool hints
  describe tools; they never grant access.
- **Every MCP tool call goes through `GatedToolset`.** Don't give an agent an
  MCP toolset that isn't wrapped in it.
- **Queued actions say they are not done.** Keep the "NOT carried out"
  result for queued tools.
- **Every run, approval and rejection is audited.**
- **Tests never call a real model.** Use the scripted fake in `tests/fakes.py`.
