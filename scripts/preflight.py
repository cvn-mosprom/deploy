#!/usr/bin/env python3
"""Environment gate: no secret values are printed."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def check(env):
    errors = []
    for name in ("POSTGRES_ADMIN_PASSWORD", "GRAFANA_PASSWORD", "POSTGRES_PASSWORD", "MIGRATION_PASSWORD", "REDIS_PASSWORD", "INTERNAL_TOKEN", "BOT_TOKEN"):
        value = env.get(name, "")
        if len(value) < 24 or any(token in value.lower() for token in ("changeme", "replace-me", "dev-internal", "example")):
            errors.append(f"{name}: missing or placeholder secret")
    if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,}", env.get("BOT_TOKEN", "")):
        errors.append("BOT_TOKEN: valid bot token format required")
    if env.get("APP_ENV") != "prod" or env.get("DEV_AUTH", "0") != "0":
        errors.append("production security mode required for staging and production")
    if not env.get("WEBAPP_URL", "").startswith("https://"):
        errors.append("WEBAPP_URL: HTTPS required")
    if env.get("POSTGRES_USER") != "mosprom_app":
        errors.append("POSTGRES_USER must be mosprom_app")
    for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        url = urlsplit(env.get(name, ""))
        if not url.hostname or not url.password:
            errors.append(f"{name}: explicit authenticated endpoint required")
    if env.get("DATABASE_URL") == env.get("MIGRATION_DATABASE_URL"):
        errors.append("application and migration roles must differ")
    for origin in env.get("CORS_ORIGINS", "").split(","):
        if not origin.startswith("https://") or "*" in origin:
            errors.append("CORS_ORIGINS: explicit HTTPS origins required")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    problems = check(read_env(args.env_file))
    print(json.dumps({"ok": not problems, "errors": problems}))
    raise SystemExit(bool(problems))
