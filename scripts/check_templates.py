#!/usr/bin/env python3
"""Render all four reference nodes locally and validate their actual Compose/YAML."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='mosprom-template-check-') as folder:
        root = Path(folder)
        variables = root / 'vars.json'
        variables.write_text(json.dumps({'render_root': str(root / 'render'), 'ansible_python_interpreter': sys.executable}))
        env = {**os.environ, 'ANSIBLE_REMOTE_TEMP': str(root / 'remote'), 'ANSIBLE_LOCAL_TEMP': str(root / 'local')}
        subprocess.run(['ansible-playbook', '-i', str(ROOT / 'ansible/inventory.example.yml'),
                        '-e', '@' + str(ROOT / 'ansible/templates/vault.example.yml'), '-e', '@' + str(variables),
                        str(ROOT / 'tests/render-playbook.yml')], check=True, env=env, stdout=subprocess.DEVNULL)
        for node in ('msk-1', 'kzn', 'spb', 'msk-2'):
            directory = root / 'render' / node
            content = (directory / 'compose.yml').read_text()
            data = yaml.safe_load(content)
            if data['name'] != 'mosprom-staging-ha':
                raise SystemExit('inventory environment was shadowed by an Ansible keyword')
            if ('etcd' in data['services']) != (node != 'msk-2'):
                raise SystemExit('DCS placement does not match the three-node quorum')
            for config in ('patroni.yml', 'alertmanager.yml'):
                yaml.safe_load((directory / config).read_text())
            patroni = yaml.safe_load((directory / 'patroni.yml').read_text())
            if patroni['bootstrap']['dcs']['synchronous_mode'] is not False or patroni['watchdog']['mode'] != 'required':
                raise SystemExit('unsafe Patroni failover configuration')
            if 'ENVIRONMENT=staging\n' not in (directory / 'runtime.env').read_text():
                raise SystemExit('runtime environment was rendered incorrectly')
            images = root / (node + '.env')
            images.write_text(''.join(f'{name}_IMAGE=example.invalid/{name.lower()}@sha256:{"a" * 64}\n'
                for name in sorted(set(re.findall(r'\$\{([A-Z_]+)_IMAGE', content)))))
            subprocess.run(['docker', 'compose', '--env-file', str(images), '-f', str(directory / 'compose.yml'), 'config', '--quiet'], check=True)
        print('all four node templates and rendered Compose configurations validated locally')


if __name__ == '__main__':
    main()
