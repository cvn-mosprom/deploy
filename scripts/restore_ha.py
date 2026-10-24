#!/usr/bin/env python3
"""Restore pgBackRest into a new private Docker network and check application readiness."""
import argparse
import datetime
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from preflight import read_env
from release import validate, verify


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state", type=Path)
    parser.add_argument("--target-time")
    parser.add_argument("--output", type=Path, default=Path("restore-results.json"))
    args = parser.parse_args()
    if args.target_time:
        target = datetime.datetime.fromisoformat(args.target_time)
        if target.tzinfo is None:
            raise SystemExit("PITR target must include a timezone")
    started = time.monotonic()
    data = validate(json.loads((args.state / "current.json").read_text()))
    verify(data)
    env = {**os.environ, **read_env(args.state / ".env")}
    image = data["external"]["patroni"]
    prefix = "mosprom-restore-" + uuid.uuid4().hex[:10]
    network = prefix
    containers = [prefix + "-pg", prefix + "-sim", prefix + "-redis", prefix + "-api"]
    pg, sim, redis, api = containers
    with tempfile.TemporaryDirectory(prefix="mosprom-restore-") as folder:
        mount = f"{folder}:/restore"
        config = f'{args.state / "ha/pgbackrest.conf"}:/etc/pgbackrest/pgbackrest.conf:ro'
        try:
            docker("network", "create", network, stdout=subprocess.DEVNULL)
            docker("run", "--rm", "--user", "0", "-v", mount, "--entrypoint", "chown", image, "999:999", "/restore")
            restore = ["run", "--rm", "-v", mount, "-v", config, "--entrypoint", "pgbackrest", image,
                       "--stanza=mosprom", "--pg1-path=/restore", "--target-action=promote"]
            if args.target_time:
                restore += ["--type=time", "--target=" + args.target_time]
            docker(*restore, "restore")
            # Existing production pg_hba is replaced only inside this temporary restored directory.
            hba = Path(folder) / "test_hba.conf"
            hba.write_text("local all all trust\nhost all all 0.0.0.0/0 scram-sha-256\n")
            docker("run", "-d", "--name", pg, "--network", network, "--network-alias", "restore-pg", "-v", mount, "-v", config,
                   "--entrypoint", "postgres", image, "-D", "/restore", "-c", "listen_addresses=*", "-c", "ssl=off", "-c", "archive_mode=off",
                   "-c", "primary_conninfo=", "-c", "hba_file=/restore/test_hba.conf", stdout=subprocess.DEVNULL)
            for _ in range(120):
                if subprocess.run(["docker", "exec", pg, "pg_isready", "-U", "postgres"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(1)
            docker("exec", pg, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "mosprom", "-c",
                   "SELECT count(*) FROM users; SELECT count(*) FROM factories; SELECT version_num FROM alembic_version;")
            docker("run", "-d", "--name", sim, "--network", network, "--network-alias", "restore-sim",
                   data["images"]["sim"]["repository"] + "@" + data["images"]["sim"]["digest"], stdout=subprocess.DEVNULL)
            docker("run", "-d", "--name", redis, "--network", network, "--network-alias", "restore-redis", data["external"]["redis"], stdout=subprocess.DEVNULL)
            env.update(DATABASE_URL=f'postgresql+asyncpg://mosprom_app:{env["POSTGRES_PASSWORD"]}@restore-pg:5432/mosprom',
                       REDIS_URL="redis://restore-redis:6379/0", REDIS_SENTINEL_NODES="", DB_TLS="0", PGBOUNCER="0", SIM_URL="http://restore-sim:8080")
            flags = [item for key in ("DATABASE_URL", "REDIS_URL", "REDIS_SENTINEL_NODES", "DB_TLS", "PGBOUNCER", "SIM_URL", "BOT_TOKEN", "INTERNAL_TOKEN", "WEBAPP_URL", "CORS_ORIGINS") for item in ("-e", key)]
            docker("run", "-d", "--name", api, "--network", network, *flags, "-e", "APP_ENV=prod", "-e", "DEV_AUTH=0",
                   data["images"]["api"]["repository"] + "@" + data["images"]["api"]["digest"], env=env, stdout=subprocess.DEVNULL)
            for _ in range(60):
                response = subprocess.run(["docker", "exec", api, "python", "-c", "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"], capture_output=True, text=True)
                if response.returncode == 0 and json.loads(response.stdout).get("status") == "ready":
                    break
                time.sleep(2)
            else:
                raise RuntimeError("restored application did not become ready")
            args.output.write_text(json.dumps({"restored": True, "applicationReady": True, "releaseId": data["releaseId"],
                                                "durationSeconds": time.monotonic() - started, "targetTime": args.target_time}, indent=2) + "\n")
        finally:
            for container in containers:
                subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Temporary restored files belong to PostgreSQL UID; clean only this dedicated bind mount.
            subprocess.run(["docker", "run", "--rm", "--user", "0", "-v", mount, "--entrypoint", "sh", image,
                            "-ec", "find /restore -mindepth 1 -delete"], check=True)


if __name__ == "__main__":
    main()
