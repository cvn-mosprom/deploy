#!/usr/bin/env python3
"""Send only a validated manifest and an ephemeral read token over pinned SSH."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from prototype_release import validate, verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    data = validate(json.loads(args.manifest.read_text()))
    verify(data)
    host = os.environ['PROTOTYPE_SSH_HOST']
    user = os.environ.get('PROTOTYPE_SSH_USER', 'mosprom-cd')
    if not re.fullmatch(r'[a-z0-9.-]+', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise SystemExit('invalid SSH target')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='mosprom-cd-') as temporary:
        key = Path(temporary) / 'key'
        known = Path(temporary) / 'known_hosts'
        key.write_text(os.environ['PROTOTYPE_SSH_KEY'].strip() + '\n')
        known.write_text(os.environ['PROTOTYPE_SSH_KNOWN_HOSTS'].strip() + '\n')
        payload = json.dumps({'release': data, 'registryToken': os.environ['GH_TOKEN']}).encode()
        subprocess.run(['ssh', '-F', '/dev/null', '-i', str(key), '-o', 'IdentitiesOnly=yes',
                        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'UserKnownHostsFile=' + str(known), '-o', 'ConnectTimeout=15',
                        user + '@' + host, 'deploy'], input=payload, check=True, timeout=900)


if __name__ == '__main__':
    main()
