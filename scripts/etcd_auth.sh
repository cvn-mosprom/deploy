#!/usr/bin/env bash
set -euo pipefail
state="$1"
environment="$2"
image="$(sed -n 's/^ETCD_IMAGE=//p' "${state}/images.env")"
wg_ip="$(sed -n 's/^WG_IP=//p' "${state}/.env")"
ctl() {
  docker run --rm --network host --user 10005:10005 --group-add 20000 \
    -v "${state}/tls/ca.crt:/tls/ca.crt:ro" \
    -v "${state}/tls/root.crt:/tls/root.crt:ro" \
    -v "${state}/tls/root.key:/tls/root.key:ro" \
    --entrypoint /usr/local/bin/etcdctl "$image" --endpoints="https://${wg_ip}:2379" \
    --cacert=/tls/ca.crt --cert=/tls/root.crt --key=/tls/root.key "$@"
}
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
