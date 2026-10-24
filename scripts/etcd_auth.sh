#!/usr/bin/env bash
set -euo pipefail
state="$1"
environment="$2"
dc=(docker compose --env-file "${state}/images.env" -f "${state}/ha/compose.yml")
ctl() { "${dc[@]}" exec -T etcd etcdctl --cacert=/tls/ca.crt --cert=/tls/root.crt --key=/tls/root.key "$@"; }
for _ in $(seq 1 60); do
  if ctl endpoint health >/dev/null 2>&1; then break; fi
  sleep 2
done
for name in root patroni bot; do
  if ! ctl user get "$name" >/dev/null 2>&1; then ctl user add "$name" --no-password; fi
  if ! ctl role get "$name" >/dev/null 2>&1; then ctl role add "$name"; fi
  ctl user grant-role "$name" "$name"
done
ctl role grant-permission patroni readwrite "/service/mosprom-${environment}/" --prefix
ctl role grant-permission bot readwrite "/mosprom/${environment}/bot"
ctl auth enable
