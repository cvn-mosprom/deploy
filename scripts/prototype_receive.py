#!/usr/bin/env python3
"""Root-owned forced command: update four services in one fixed Compose project."""
from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from prototype_release import configuration_digest, render, validate, verify

ROOT = Path('/opt/mosprom-prototype')
CONFIG = ROOT / 'deploy'
STATE = ROOT / 'cd'
RUNTIME = ROOT / 'runtime.env'
SERVICES = ('sim', 'api', 'bot', 'web')


def dc(images: Path | None, *arguments: str):
    command = ['docker', 'compose', '--project-name', 'mosprom-prototype', '--env-file', str(RUNTIME)]
    if images is not None:
        command += ['--env-file', str(images)]
    return command + ['-f', str(CONFIG / 'compose/prototype.yml'), *arguments]


def run(command, *, env, **kwargs):
    return subprocess.run(command, check=True, env=env, **kwargs)


def valid_registry_token(token):
    # GitHub tokens are opaque and may use a JWT format. Never assume a prefix or fixed length.
    return isinstance(token, str) and 20 <= len(token) <= 8192 and all(33 <= ord(char) <= 126 for char in token)


def database_version(*, env):
    return subprocess.check_output(dc(None, 'exec', '-T', 'db', 'psql', '-U', 'mosprom_admin',
        '-d', 'mosprom', '-Atc', 'SELECT version_num FROM alembic_version ORDER BY version_num'),
        text=True, env=env).strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('readiness redirect rejected')


def reconcile_telegram_menu():
    runtime = dict(line.partition('=')[::2] for line in RUNTIME.read_text().splitlines()
                   if line and not line.startswith('#'))
    expected_url = 'https://ochakovo.velikoss.ru/app'
    if runtime.get('WEBAPP_URL') != expected_url:
        raise ValueError('prototype WEBAPP_URL must point to /app')
    proxy = runtime.get('TELEGRAM_PROXY_URL')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy} if proxy else {}), NoRedirect())

    def call(method, body=None):
        request = urllib.request.Request('https://api.telegram.org/bot' + runtime['BOT_TOKEN'] + '/' + method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=20) as response:
            data = json.load(response)
        if not data.get('ok'):
            raise ValueError('Telegram API rejected menu configuration')
        return data['result']

    if call('getMe').get('username', '').lower() != 'cvnprombot':
        raise ValueError('unexpected prototype bot identity')
    menu = call('getChatMenuButton')
    if menu.get('web_app', {}).get('url') != expected_url:
        call('setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Играть',
                                                  'web_app': {'url': expected_url}}})
        if call('getChatMenuButton').get('web_app', {}).get('url') != expected_url:
            raise ValueError('Telegram menu did not converge')


def smoke(release_id: str):
    opener = urllib.request.build_opener(NoRedirect())
    origin = 'http://127.0.0.1:18081'
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with opener.open(origin + '/ready', timeout=5) as response:
                if json.load(response).get('status') != 'ready':
                    raise ValueError('API not ready')
            with opener.open(origin + '/routing/ping?nonce=cd', timeout=5) as response:
                ping = json.load(response)
                if ping.get('releaseId') != release_id:
                    raise ValueError('old release still serves requests')
            with opener.open(origin + '/', timeout=5) as response:
                if b'id="hero-heading"' not in response.read(512 * 1024):
                    raise ValueError('root landing missing')
            with opener.open(origin + '/app', timeout=5) as response:
                if b'_app/' not in response.read(512 * 1024):
                    raise ValueError('game entry missing')
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError('prototype smoke failed')


def deploy(data: dict, token: str, registry_user: str = 'github-actions'):
    validate(data)
    if configuration_digest(CONFIG) != data['configurationSha256']:
        raise ValueError('configuration drift: review and bootstrap server configuration separately')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='registry-', dir=STATE) as temporary:
            auth = base64.b64encode((registry_user + ':' + token).encode()).decode()
            (Path(temporary) / 'config.json').write_text(json.dumps({'auths': {'ghcr.io': {'auth': auth}}}))
            env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root', 'DOCKER_CONFIG': temporary,
                   'PROTOTYPE_ENV_FILE': str(RUNTIME)}
            verify(data, env=env)
            release_dir = STATE / 'releases' / data['releaseId']
            release_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            manifest = release_dir / 'release.json'
            if manifest.exists() and json.loads(manifest.read_text()) != data:
                raise ValueError('release id already contains different coordinates')
            images = release_dir / 'images.env'
            images.write_text(render(data))
            manifest.write_text(json.dumps(data, indent=2) + '\n')
            current = STATE / 'current.json'
            current_images = STATE / 'current-images.env'
            if current.exists() and json.loads(current.read_text()) == data:
                smoke(data['releaseId'])
                reconcile_telegram_menu()
                print(json.dumps({'status': 'already-deployed', 'releaseId': data['releaseId']}))
                return
            for image in data['images'].values():
                reference = image['repository'] + '@' + image['digest']
                run(['docker', 'pull', '--quiet', reference], env=env)
                architecture = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Architecture}}',
                                                       reference], text=True, env=env).strip()
                if architecture != 'amd64':
                    raise ValueError('linux/amd64 required')
            run(dc(images, 'config', '--quiet'), env=env)
            before = database_version(env=env)
            backup = release_dir / ('before-' + str(int(time.time())) + '.dump')
            with backup.open('xb') as output:
                run(dc(None, 'exec', '-T', 'db', 'pg_dump', '-U', 'mosprom_admin', '-d', 'mosprom',
                       '--format=custom', '--no-owner', '--no-acl'), env=env, stdout=output)
            if backup.stat().st_size < 100:
                raise ValueError('empty pre-deployment backup')
            prior_images = current_images if current_images.exists() else None
            try:
                run(dc(prior_images, 'stop', 'bot'), env=env)
                run(dc(images, 'run', '--rm', '--no-deps', 'migrate'), env=env)
                run(dc(images, 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', *SERVICES), env=env)
                smoke(data['releaseId'])
                time.sleep(10)
                bot = subprocess.check_output(dc(images, 'ps', '--status', 'running', '--services', 'bot'),
                                              text=True, env=env).strip()
                if bot != 'bot':
                    raise RuntimeError('bot stopped after rollout')
                reconcile_telegram_menu()
            except Exception:
                # The exact Alembic version must be unchanged. Never restore a database automatically.
                if database_version(env=env) == before:
                    run(dc(prior_images, 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', *SERVICES), env=env)
                else:
                    print('Schema changed: automatic image rollback blocked; controlled recovery required', file=sys.stderr)
                raise
            if current.exists():
                (STATE / 'previous.json').write_bytes(current.read_bytes())
            for target, value in ((current_images, render(data)), (current, json.dumps(data, indent=2) + '\n')):
                pending = target.with_suffix(target.suffix + '.next')
                pending.write_text(value)
                pending.replace(target)
            print(json.dumps({'status': 'success', 'releaseId': data['releaseId'], 'backup': backup.name}))


def main():
    os.umask(0o077)
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit('use the installed forced command')
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise SystemExit('request too large')
    request = json.loads(raw)
    token = request['registryToken']
    if not valid_registry_token(token):
        raise SystemExit('invalid ephemeral registry token')
    registry_user = request['registryUser']
    if not isinstance(registry_user, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\[\]-]{0,99}', registry_user):
        raise SystemExit('invalid registry actor')
    try:
        deploy(request['release'], token, registry_user)
    except Exception as error:
        # Do not serialize the input, environment or subprocess output, which may contain credentials.
        print('prototype deployment failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
