#!/usr/bin/env bash
set -euo pipefail
infra_root="$(cd "$(dirname "$0")/.." && pwd)"
export PROTOTYPE_ENV_FILE="${PROTOTYPE_ENV_FILE:-/opt/mosprom-prototype/runtime.env}"
command=(docker compose --project-name mosprom-prototype --env-file "$PROTOTYPE_ENV_FILE" -f "$infra_root/compose/prototype.yml")
case "${1:-status}" in
  up) "${command[@]}" config --quiet; "${command[@]}" up -d --no-build --wait --wait-timeout 180 ;;
  stop) "${command[@]}" stop ;;
  status) "${command[@]}" ps ;;
  seed) "${command[@]}" exec -T api python -m app.seed_bots ;;
  *) echo "usage: $0 [up|stop|status|seed]" >&2; exit 2 ;;
esac
