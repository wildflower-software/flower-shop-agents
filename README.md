# Flower Shop Agents

A small, readable reference implementation of **worker-agent orchestration** for a small business, from [Wildflower Software](https://wildflowersoftware.com).

One coordinator agent talks to the owner. It delegates to four narrow worker agents. Anything that spends money, commits to a customer or goes public passes through an approval gate before it happens.

![Architecture](docs/architecture.svg)

The flower shop is a teaching example. The same pattern runs a clinic front desk, a property manager's inbox or an enterprise operations team; the workers and tools change, the shape does not.

## What's inside

| Path | What it does |
| --- | --- |
| `shop_agents/workers.py` | The four workers: a job description and an allow-list of tools each |
| `shop_agents/tools.py` | Shop tools, each marked safe (runs now) or `requires_approval` |
| `shop_agents/approval.py` | The approval gate and audit trail |
| `shop_agents/runner.py` | The tool-use loop for one worker |
| `shop_agents/coordinator.py` | The coordinator, whose only tools are the workers |
| `main.py` | Command-line entry point with interactive approvals |
| `tests/` | Offline tests using a scripted fake client, no API key needed |

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here

python main.py                                  # the morning brief
python main.py "Quote the June wedding inquiry"  # any request
```

After the coordinator answers, you'll be asked to approve or reject each queued action. Every decision is appended to `audit.jsonl`.

Set `SHOP_AGENTS_MODEL` to choose a different Claude model.

## Test it

```bash
pytest
```

The tests check the guarantees that matter: read-only tools run immediately, risky tools are queued and never executed without approval, a rejected action never runs, and a worker cannot call a tool outside its job.

## Design choices

- **Narrow workers.** Each worker gets a short job description and only the tools that job needs. Narrow agents are easier to test, cheaper to run and easier to trust.
- **The coordinator has no direct access.** Its only tools are the workers, so every real action flows through a worker's allow-list and the gate.
- **Approval is enforced in code, not in the prompt.** The model is told about approvals, but the gate is what actually stops an action.
- **Honest tool results.** A queued action returns "NOT carried out", so the agent reports it as waiting rather than done.
- **Audit by default.** Every automatic run, queue, approval and rejection is logged.

## Taking it to production

The demo shop lives in memory. In a real deployment you would replace the tool functions with your POS, email, calendar and supplier integrations (often through MCP connectors), move the approval queue to somewhere the owner already works (Slack, email, a phone notification), and run the morning brief on a schedule.

For larger organizations, the same structure extends with per-role permissions, persistent audit storage, evaluation suites for each worker and deployment inside your own cloud.

Need help adapting this to your business? [Get in touch with Wildflower Software](https://wildflowersoftware.com).

## License

MIT
