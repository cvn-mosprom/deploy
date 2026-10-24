#!/usr/bin/env python3
"""Serialized, digest-only deployments. Database restore is never automatic."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from preflight import check, read_env
from release import render, validate, verify

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, env=None, **kwargs):
    return subprocess.run(command, check=True, env=env, **kwargs)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("readiness redirect rejected")


def smoke(url: str, timeout: int = 120):
    if not url.startswith("https://"):
        raise ValueError("readiness must use HTTPS")
    opener = urllib.request.build_opener(NoRedirect())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url.rstrip("/") + "/ready", timeout=5) as response:
                if response.status == 200 and json.load(response).get("status") == "ready":
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError("readiness gate failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    env = read_env(args.env_file)
    problems = check(env)
    if problems:
        raise SystemExit("preflight: " + "; ".join(problems))
    state = Path(env["STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    with (state / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current_path = state / "current.json"
        previous_path = state / "previous.json"
        current = json.loads(current_path.read_text()) if current_path.exists() else None
        target = validate(json.loads((previous_path if args.rollback else args.manifest).read_text()))
        if args.rollback and current and not current["schemaCompatibility"]["rollbackSafe"]:
            raise SystemExit("schema incompatible: controlled database recovery required")
        verify(target)
        if current == target:
            print("release already deployed")
            return
        if env.get("ETCD_ENDPOINTS"):
            raise SystemExit("use the serialized Ansible HA rollout for distributed deployments")
        release_dir = state / "releases" / target["releaseId"]
        config = release_dir / "config"
        if not config.exists():
            release_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT, config, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "node_modules"))
        images = release_dir / "images.env"
        images.write_text(render(target))

        def dc(data, *command):
            directory = state / "releases" / data["releaseId"]
            return ["docker", "compose", "--env-file", str(args.env_file.resolve()), "--env-file", str(directory / "images.env"),
                    "-f", str(directory / "config/compose/compose.yml"), *command]

        process_env = {**os.environ, **env}
        run(dc(target, "config", "--quiet"), env=process_env)
        run(dc(target, "pull"), env=process_env)
        if current:
            # A failed/off-host backup aborts before migrations or any service changes.
            run(["python3", str(ROOT / "scripts/backup.py"), str(current_path), "--env-file", str(args.env_file)], env=process_env)
        run(dc(target, "up", "-d", "--wait", "db", "redis"), env=process_env)
        try:
            if not args.rollback:
                run(dc(target, "run", "--rm", "migrate"), env=process_env)
            run(dc(target, "up", "-d", "--wait", "--wait-timeout", "180", "--remove-orphans", "--scale", "api=" + env.get("API_REPLICAS", "1"), "--scale", "sim=" + env.get("SIM_REPLICAS", "1")), env=process_env)
            smoke(env["WEBAPP_URL"])
        except Exception:
            if current and target["schemaCompatibility"]["rollbackSafe"]:
                run(dc(current, "up", "-d", "--wait", "--wait-timeout", "180", "--remove-orphans", "--scale", "api=" + env.get("API_REPLICAS", "1"), "--scale", "sim=" + env.get("SIM_REPLICAS", "1")), env=process_env)
                smoke(env["WEBAPP_URL"])
            else:
                print("automatic image rollback disabled: schema compatibility not established")
            raise
        if current:
            previous_path.write_text(json.dumps(current, indent=2) + "\n")
        temporary = state / "current.json.tmp"
        temporary.write_text(json.dumps(target, indent=2) + "\n")
        temporary.replace(current_path)
        link = state / "current-config.next"
        link.unlink(missing_ok=True)
        link.symlink_to(config, target_is_directory=True)
        link.replace(state / "current-config")
        with (state / "deployments.jsonl").open("a") as history:
            history.write(json.dumps({"timestamp": time.time(), "releaseId": target["releaseId"], "rollback": args.rollback}) + "\n")


if __name__ == "__main__":
    main()
