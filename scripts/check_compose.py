#!/usr/bin/env python3
"""Parse both profiles using synthetic test coordinates, then prove missing pins fail."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {**os.environ, "ENVIRONMENT": "test", "STATE_DIR": tempfile.gettempdir(), "DOMAIN": "test.example.com", "ROUTING_ZONE": "example.com",
           "WEBAPP_URL": "https://test.example.com", "CORS_ORIGINS": "https://test.example.com", "ACME_EMAIL": "ops@example.com",
           "DATABASE_URL": "postgresql+asyncpg://test:test@db/test", "MIGRATION_DATABASE_URL": "postgresql+asyncpg://migrate:test@db/test",
           "REDIS_URL": "redis://redis", "POSTGRES_ADMIN_PASSWORD": "synthetic", "POSTGRES_PASSWORD": "synthetic", "MIGRATION_PASSWORD": "synthetic", "REDIS_PASSWORD": "synthetic",
           "BOT_TOKEN": "synthetic", "INTERNAL_TOKEN": "synthetic", "GRAFANA_PASSWORD": "synthetic", "WG_IP": "10.60.0.11",
           "RELEASE_ID": "test", "FRONTEND_REVISION": "f" * 40}
    for name in ["API", "BOT", "SIM", "WEB", "DISCOVERY", "PATRONI", "PGBACKREST"]:
        env[name + "_IMAGE"] = "example.invalid/test@sha256:" + "a" * 64
    for name, value in json.loads((ROOT / "images.lock.json").read_text()).items():
        env[name.upper() + "_IMAGE"] = value
    command = ["docker", "compose", "-f", str(ROOT / "compose/compose.yml")]
    for extra in [[], ["-f", str(ROOT / "compose/ha.yml")]]:
        subprocess.run([*command, *extra, "--profile", "single", "--profile", "monitoring", "config", "--quiet"], env=env, check=True)
    env.pop("API_IMAGE")
    failed = subprocess.run([*command, "config", "--quiet"], env=env, capture_output=True)
    if failed.returncode == 0 or b"API_IMAGE" not in failed.stderr:
        raise SystemExit("Compose did not fail closed for a missing image pin")
    print("single/HA profiles validated; missing image pin rejected")


if __name__ == "__main__":
    main()
