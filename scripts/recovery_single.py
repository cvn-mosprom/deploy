#!/usr/bin/env python3
"""Exercise an off-host snapshot, not the VM's local dump."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from preflight import read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('state', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    env = {**os.environ, **read_env(args.state / '.env')}
    snapshots = json.loads(subprocess.check_output(['restic', 'snapshots', '--json'], env=env, text=True))
    matching = [item for item in snapshots if 'mosprom-db' in item.get('tags', [])]
    if not matching:
        raise SystemExit('no off-host mosprom-db snapshot')
    snapshot = max(matching, key=lambda item: item['time'])
    with tempfile.TemporaryDirectory(prefix='mosprom-offhost-recovery-') as folder:
        subprocess.run(['restic', 'restore', snapshot['id'], '--target', folder], env=env, check=True)
        dumps = list(Path(folder).rglob('*.dump'))
        if len(dumps) != 1:
            raise SystemExit('one database dump per snapshot required')
        subprocess.run(['python3', str(Path(__file__).with_name('backup.py')), str(args.state / 'current.json'),
                        '--env-file', str(args.state / '.env'), '--restore-test', str(dumps[0])], env=env, check=True)


if __name__ == '__main__':
    main()
