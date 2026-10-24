#!/usr/bin/env python3
"""The jury prototype has a separate release contract and trust identity from HA."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

PROFILE = 'prototype-v1'
BRANCH = 'main'
IDENTITY = f'https://github.com/cvn-mosprom/backend/.github/workflows/ci.yml@refs/heads/{BRANCH}'
ISSUER = 'https://token.actions.githubusercontent.com'
NAMES = {'api', 'bot', 'sim', 'web'}
SHA = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
CONFIG_FILES = ('compose/prototype.yml', 'compose/prototype.Caddyfile', 'compose/init-db.sql',
                'scripts/prototype-backup.sh')


def configuration_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name in CONFIG_FILES:
        digest.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    return digest.hexdigest()


def validate(data: dict) -> dict:
    if data.get('version') != 1 or data.get('profile') != PROFILE:
        raise ValueError('only isolated prototype releases are accepted')
    for name in ('backendSha', 'frontendSha', 'deploySha'):
        if not SHA.fullmatch(data.get(name, '')):
            raise ValueError(f'invalid {name}')
    for name in ('runId', 'runAttempt'):
        if not re.fullmatch(r'[1-9][0-9]{0,14}', data.get(name, '')):
            raise ValueError('invalid build run coordinates')
    base_id = 'prototype-' + data['backendSha'] + '-' + data['runId'] + '-' + data['runAttempt']
    if data.get('releaseId') not in (base_id, base_id + '-' + data['deploySha'][:12]):
        raise ValueError('release id must identify the backend commit')
    if not re.fullmatch(r'[0-9a-f]{64}', data.get('configurationSha256', '')):
        raise ValueError('configuration hash required')
    if set(data.get('images', {})) != NAMES:
        raise ValueError('exactly api/bot/sim/web required; infrastructure changes are forbidden')
    for name, image in data['images'].items():
        if image.get('repository') != 'ghcr.io/cvn-mosprom/' + name or not DIGEST.fullmatch(image.get('digest', '')):
            raise ValueError('unexpected repository or mutable image')
        if image.get('sourceSha') != data['backendSha'] or image.get('frontendSha') != data['frontendSha']:
            raise ValueError('mixed source revisions')
        if image.get('profile') != PROFILE:
            raise ValueError('image was not built for the prototype')
        if image.get('runId') != data['runId'] or image.get('runAttempt') != data['runAttempt']:
            raise ValueError('mixed CI runs')
    return data


def envelopes(raw: str):
    decoder = json.JSONDecoder()
    remaining = raw.strip()
    while remaining:
        item, consumed = decoder.raw_decode(remaining)
        yield from item if isinstance(item, list) else [item]
        remaining = remaining[consumed:].lstrip()


def verify(data: dict, *, env=None):
    validate(data)
    expected = {'backendSha': data['backendSha'], 'frontendSha': data['frontendSha'], 'profile': PROFILE,
                'runId': data['runId'], 'runAttempt': data['runAttempt']}
    for image in data['images'].values():
        reference = image['repository'] + '@' + image['digest']
        options = ['--certificate-identity', IDENTITY, '--certificate-oidc-issuer', ISSUER]
        subprocess.run(['cosign', 'verify', *options, reference], check=True, env=env, stdout=subprocess.DEVNULL)
        raw = subprocess.check_output(['cosign', 'verify-attestation', '--type', 'slsaprovenance1',
                                       *options, reference], text=True, env=env)
        if not any(json.loads(base64.b64decode(item['payload']))['predicate'].get('buildDefinition', {}).get('externalParameters', {}).get('mospromSource') == expected
                   for item in envelopes(raw)):
            raise ValueError('signed provenance does not match prototype sources')


def create(artifacts: Path, *, backend_sha: str, frontend_sha: str, root: Path, deploy_sha: str):
    images = {}
    for path in artifacts.rglob('image.json'):
        image = json.loads(path.read_text())
        name = image.pop('name')
        if name in images:
            raise ValueError('duplicate image artifact')
        images[name] = image
    first = next(iter(images.values()))
    run_id, attempt = first['runId'], first['runAttempt']
    return validate({'version': 1, 'profile': PROFILE, 'releaseId': 'prototype-' + backend_sha + '-' + run_id + '-' + attempt + '-' + deploy_sha[:12],
        'runId': run_id, 'runAttempt': attempt,
        'backendSha': backend_sha, 'frontendSha': frontend_sha, 'deploySha': deploy_sha,
        'configurationSha256': configuration_digest(root), 'images': images})


def render(data: dict) -> str:
    validate(data)
    values = [f"RELEASE_ID={data['releaseId']}", f"FRONTEND_REVISION={data['frontendSha']}"]
    values += [f"{name.upper()}_IMAGE={image['repository']}@{image['digest']}"
               for name, image in sorted(data['images'].items())]
    return '\n'.join(values) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--backend-sha')
    parser.add_argument('--frontend-sha')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.artifacts:
        deploy_sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        data = create(args.artifacts, backend_sha=args.backend_sha, frontend_sha=args.frontend_sha,
                      root=root, deploy_sha=deploy_sha)
        args.manifest.write_text(json.dumps(data, indent=2) + '\n')
    else:
        data = validate(json.loads(args.manifest.read_text()))
    if args.verify:
        verify(data)


if __name__ == '__main__':
    main()
