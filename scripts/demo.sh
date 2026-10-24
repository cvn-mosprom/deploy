#!/usr/bin/env bash
set -euo pipefail
infra_root="$(cd "$(dirname "$0")/.." && pwd)"
backend_root="${MOSPROM_BACKEND_DIR:-$(cd "$infra_root/../backend" && pwd)}"
export DEMO_DEPLOY_DIR="$infra_root" DEMO_ENV_FILE="$infra_root/.env.demo"
if [[ ! -f "$DEMO_ENV_FILE" ]]; then
  python3 - "$infra_root/environments/demo.env.example" "$DEMO_ENV_FILE" <<'PYENV'
import os, secrets, sys
from pathlib import Path
source = Path(sys.argv[1]).read_text()
lines = [line.split('=', 1)[0] + '=' + secrets.token_hex(32) if line.endswith('=__GENERATE__') else line for line in source.splitlines()]
with os.fdopen(os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
    stream.write('\n'.join(lines) + '\n')
PYENV
fi
export SIM_COMMIT
SIM_COMMIT="$(git -C "$backend_root" rev-parse HEAD:vendor/frontend)"
command=(docker compose --project-name mosprom-demo --env-file "$DEMO_ENV_FILE" -f "$backend_root/docker-compose.yml" -f "$infra_root/compose/demo.yml")
case "${1:-up}" in
  up) "${command[@]}" up -d --build --wait --wait-timeout 300 ;;
  start) "${command[@]}" up -d --no-build --wait --wait-timeout 300 ;;
  stop) "${command[@]}" stop ;;
  status) "${command[@]}" ps ;;
  logs) "${command[@]}" logs --tail 80 ;;
  seed) "${command[@]}" exec -T api python -m app.seed_bots ;;
  *) echo "usage: $0 [up|start|stop|status|logs|seed]" >&2; exit 2 ;;
esac
