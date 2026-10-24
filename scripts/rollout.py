#!/usr/bin/env python3
"""One controlled HA rollout; credentials come from an encrypted Ansible Vault."""
import argparse
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path

from release import render, validate, verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    data = validate(json.loads(args.manifest.read_text()))
    verify(data)
    os.umask(0o077)
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache"))) / "mosprom"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (runtime / "ha-rollout.lock").open("a") as lock, tempfile.TemporaryDirectory() as tmp:
        fcntl.flock(lock, fcntl.LOCK_EX)
        folder = Path(tmp)
        images = folder / "images.env"
        images.write_text(render(data))
        archive = folder / "deploy.tar"
        subprocess.run(["git", "archive", "--format=tar", "--output", str(archive), data["deploySha"]], check=True)
        subprocess.run(["python3", "scripts/bootstrap_runtime.py", str(args.manifest), str(args.inventory), str(folder / "runtime")], check=True)
        extra = {"runtime_directory": str(folder / "runtime"), "release_manifest": data, "rendered_images": str(images), "manifest_path": str(args.manifest.resolve()),
                 "deployment_archive": str(archive)}
        variables = folder / "release.json"
        variables.write_text(json.dumps(extra))
        common = ["ansible-playbook", "-i", str(args.inventory), "-e", "@" + str(args.vault), "-e", "@" + str(variables)]
        if args.provision:
            subprocess.run([*common, "ansible/site.yml"], check=True)
        subprocess.run([*common, "ansible/rollout.yml"], check=True)


if __name__ == "__main__":
    main()
