#!/usr/bin/env python3
"""Static release/configuration checks used before any privileged job."""
import json
import re
from pathlib import Path

import yaml

from release import validate

ROOT = Path(__file__).resolve().parents[1]


def main():
    for path in ROOT.rglob("*.yml"):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        yaml.safe_load(path.read_text())
    for path in (ROOT / "releases").glob("*.json"):
        validate(json.loads(path.read_text()))
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        for action in re.findall(r"uses:\s*([^\s#]+)", path.read_text()):
            if not action.startswith("./") and not re.search(r"@[a-f0-9]{40}$", action):
                raise SystemExit(f"mutable action reference: {path.name}: {action}")
    lock = json.loads((ROOT / "images.lock.json").read_text())
    for name, image in lock.items():
        if not re.search(r"@sha256:[a-f0-9]{64}$", image):
            raise SystemExit(f"mutable image {name}")
    if set(lock) != {"python", "node", "postgres", "redis", "golang", "alpine", "haproxy", "pgbouncer", "prometheus", "grafana", "alertmanager", "etcd"}:
        raise SystemExit("image lock incomplete")
    print("YAML, release manifests, workflow pins and external image locks validated")


if __name__ == "__main__":
    main()
