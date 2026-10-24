#!/usr/bin/env bash
# Explicit root-only bootstrap; never executed by a delivery workflow.
set -euo pipefail
test "$(id -u)" -eq 0
test "$#" -eq 1
source_root="$(cd "$(dirname "$0")/.." && pwd)"
public_key="$(cat "$1")"
[[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || { echo 'Expected an ed25519 public key' >&2; exit 1; }
test -f /opt/mosprom-prototype/runtime.env
test -x /usr/local/bin/cosign
test -f /opt/mosprom-prototype/deploy/compose/prototype.yml
if ! id mosprom-cd >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/mosprom-cd --shell /bin/sh mosprom-cd
fi
test "$(id -Gn mosprom-cd)" = mosprom-cd
install -d -m 0700 /opt/mosprom-prototype/cd/lib
install -m 0644 "$source_root/scripts/prototype_release.py" "$source_root/scripts/prototype_receive.py" /opt/mosprom-prototype/cd/lib/
install -d -m 0755 /usr/local/libexec
cat > /opt/mosprom-prototype/cd/lib/entry.py <<'EOF'
import sys
sys.path.insert(0, '/opt/mosprom-prototype/cd/lib')
from prototype_receive import main
main()
EOF
cat > /usr/local/libexec/mosprom-prototype-cd <<'EOF'
#!/bin/sh
set -eu
test "$#" -eq 0
exec /usr/bin/python3 -I /opt/mosprom-prototype/cd/lib/entry.py
EOF
cat > /usr/local/libexec/mosprom-cd-entry <<'EOF'
#!/bin/sh
set -eu
test "${SSH_ORIGINAL_COMMAND:-}" = deploy
exec /usr/bin/sudo -n /usr/local/libexec/mosprom-prototype-cd
EOF
chmod 0755 /usr/local/libexec/mosprom-prototype-cd /usr/local/libexec/mosprom-cd-entry
printf '%s\n' 'mosprom-cd ALL=(root) NOPASSWD: /usr/local/libexec/mosprom-prototype-cd ""' > /etc/sudoers.d/mosprom-prototype-cd
chmod 0440 /etc/sudoers.d/mosprom-prototype-cd
visudo -cf /etc/sudoers.d/mosprom-prototype-cd
install -d -o mosprom-cd -g mosprom-cd -m 0700 /var/lib/mosprom-cd/.ssh
printf 'restrict,command="/usr/local/libexec/mosprom-cd-entry" %s\n' "$public_key" > /var/lib/mosprom-cd/.ssh/authorized_keys
chown mosprom-cd:mosprom-cd /var/lib/mosprom-cd/.ssh/authorized_keys
chmod 0600 /var/lib/mosprom-cd/.ssh/authorized_keys
echo 'Restricted prototype CD installed; no service was restarted.'
