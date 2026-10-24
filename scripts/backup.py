#!/usr/bin/env python3
"""Logical backups with mandatory encrypted off-host upload and safe restore test."""
import argparse
import datetime
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from preflight import read_env
from release import validate, verify
from restore_application import check_application


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--restore-test", type=Path)
    args = parser.parse_args()
    env = {**os.environ, **read_env(args.env_file)}
    data = validate(json.loads(args.manifest.read_text()))
    image = data["external"]["postgres"]
    prefix = ["docker", "compose", "--env-file", str(args.env_file), "--env-file", str(Path(env["STATE_DIR"]) / "releases" / data["releaseId"] / "images.env"),
              "-f", str(Path(env["STATE_DIR"]) / "releases" / data["releaseId"] / "config/compose/compose.yml")]
    if args.restore_test:
        name = "mosprom-restore-" + uuid.uuid4().hex[:12]
        verify(data)
        started = time.monotonic()
        try:
            subprocess.run(["docker", "network", "create", name], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "run", "-d", "--name", name, "--network", name, "-e", "POSTGRES_DB=mosprom", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image], check=True, stdout=subprocess.DEVNULL)
            for _ in range(60):
                if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(1)
            with args.restore_test.open("rb") as backup:
                subprocess.run(["docker", "exec", "-i", name, "pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "-U", "postgres", "-d", "mosprom"], stdin=backup, check=True)
            subprocess.run(["docker", "exec", name, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "mosprom", "-c",
                            "SELECT count(*) FROM users; SELECT count(*) FROM factories; SELECT version_num FROM alembic_version;"], check=True)
            # The restored dump deliberately omits ownership; grant only the application role.
            sql = r"""\getenv app_password APP_PASSWORD
CREATE ROLE mosprom_app LOGIN NOSUPERUSER PASSWORD :'app_password';
GRANT CONNECT ON DATABASE mosprom TO mosprom_app;
GRANT USAGE ON SCHEMA public TO mosprom_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mosprom_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mosprom_app;
"""
            subprocess.run(["docker", "exec", "-i", "-e", "APP_PASSWORD", name, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "mosprom"],
                           input=sql, text=True, env={**env, "APP_PASSWORD": env["POSTGRES_PASSWORD"]}, check=True)
            check_application(data, env, name, name, name)
            Path("restore-results.json").write_text(json.dumps({"restored": True, "applicationReady": True, "releaseId": data["releaseId"],
                "durationSeconds": time.monotonic() - started}, indent=2) + "\n")
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=False, stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "network", "rm", name], check=False, stdout=subprocess.DEVNULL)
        return
    folder = Path(env["STATE_DIR"]) / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + ".dump")
    temporary = path.with_suffix(".partial")
    with temporary.open("wb") as output:
        subprocess.run([*prefix, "exec", "-T", "db", "pg_dump", "-U", "mosprom_migrate", "-Fc", "--no-owner", "mosprom"], env=env, stdout=output, check=True)
    subprocess.run(["docker", "run", "--rm", "-i", image, "pg_restore", "--list"], stdin=temporary.open("rb"), check=True, stdout=subprocess.DEVNULL)
    temporary.replace(path)
    if not env.get("RESTIC_REPOSITORY") or not env.get("RESTIC_PASSWORD_FILE"):
        raise SystemExit("encrypted off-host restic repository is required")
    subprocess.run(["restic", "backup", "--tag", "mosprom-db", str(path)], env=env, check=True)
    status = Path(env["STATE_DIR"]) / "monitoring"
    status.mkdir(mode=0o750, exist_ok=True)
    (status / "backup.timestamp").write_text(str(time.time()))
    print(path)


if __name__ == "__main__":
    main()
