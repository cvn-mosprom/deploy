"""Start only an isolated restored application's dependencies and check readiness."""
import json
import subprocess
import time


def check_application(data, env, network, pg, prefix):
    names = [prefix + suffix for suffix in ('-sim', '-redis', '-api')]
    sim, redis, api = names
    def run(*args, **kwargs):
        return subprocess.run(['docker', *args], check=True, **kwargs)
    try:
        run('run', '-d', '--name', sim, '--network', network, data['images']['sim']['repository'] + '@' + data['images']['sim']['digest'], stdout=subprocess.DEVNULL)
        run('run', '-d', '--name', redis, '--network', network, data['external']['redis'], stdout=subprocess.DEVNULL)
        runtime = {**env, 'DATABASE_URL': f'postgresql+asyncpg://mosprom_app:{env["POSTGRES_PASSWORD"]}@{pg}:5432/mosprom',
                   'REDIS_URL': f'redis://{redis}:6379/0', 'REDIS_SENTINEL_NODES': '', 'REDIS_TLS': '0',
                   'DB_TLS': '0', 'PGBOUNCER': '0', 'SIM_URL': f'http://{sim}:8080', 'FRONTEND_REVISION': data['frontendSha']}
        flags = [item for key in ('DATABASE_URL', 'REDIS_URL', 'REDIS_SENTINEL_NODES', 'REDIS_TLS', 'DB_TLS', 'PGBOUNCER', 'SIM_URL',
                                 'BOT_TOKEN', 'INTERNAL_TOKEN', 'WEBAPP_URL', 'CORS_ORIGINS', 'FRONTEND_REVISION') for item in ('-e', key)]
        run('run', '-d', '--name', api, '--network', network, *flags, '-e', 'APP_ENV=prod', '-e', 'DEV_AUTH=0',
            data['images']['api']['repository'] + '@' + data['images']['api']['digest'], env=runtime, stdout=subprocess.DEVNULL)
        for _ in range(60):
            response = subprocess.run(['docker', 'exec', api, 'python', '-c',
                "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"], capture_output=True, text=True)
            if response.returncode == 0 and json.loads(response.stdout).get('status') == 'ready':
                return
            time.sleep(2)
        raise RuntimeError('restored application did not become ready')
    finally:
        for name in names:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
