#!/usr/bin/env bash
set -euo pipefail
manifest="$(realpath "$1")"
python3 scripts/release.py "$manifest" --verify
python3 scripts/deployment_status.py "$manifest" in_progress
finish() {
  status=$?
  if [[ "$status" -eq 0 ]]; then state=success; else state=failure; fi
  python3 scripts/deployment_status.py "$manifest" "$state"
}
trap finish EXIT
if [[ "${DEPLOYMENT_TOPOLOGY:-single}" == single ]]; then
  python3 scripts/deploy.py "$manifest" --env-file "/srv/mosprom-${TARGET_ENVIRONMENT}/.env"
elif [[ "$DEPLOYMENT_TOPOLOGY" == ha ]]; then
  python3 scripts/rollout.py "$manifest" --inventory "/etc/mosprom/${TARGET_ENVIRONMENT}/inventory.yml" --vault "/etc/mosprom/${TARGET_ENVIRONMENT}/vault.yml"
else
  echo 'Unknown deployment topology' >&2
  exit 1
fi
