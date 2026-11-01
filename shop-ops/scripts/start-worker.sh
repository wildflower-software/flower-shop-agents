#!/usr/bin/env bash
# Render background worker: set up the database on the persistent disk if needed,
# then stay up and run the shop's scheduled flows (Prefect Cloud keeps the schedule).
set -euo pipefail

DB="${SHOP_OPS_DB:?set SHOP_OPS_DB to a path on the persistent disk}"

if [[ ! -f "$DB" ]]; then
  uv run --frozen shop-ops init
  if [[ "${SHOP_OPS_SEED_SYNTHETIC:-0}" == "1" ]]; then
    # Placeholder history, tagged data_source='synthetic'; notes will say so.
    uv run --frozen shop-ops generate
  fi
else
  uv run --frozen shop-ops reload-config
fi

exec uv run --frozen python -m shop_ops.flows serve
