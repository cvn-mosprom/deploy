#!/usr/bin/env python3
"""Static release/configuration checks used before any privileged job."""
import json
import re
from pathlib import Path

import yaml

from release import validate

ROOT = Path(__file__).resolve().parents[1]


class ComposeLoader(yaml.SafeLoader):
    """Safe YAML plus Compose's documented merge-control tags."""


def compose_value(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return None if node.value in ("", "null", "~") else loader.construct_scalar(node)


for tag in ("!override", "!reset"):
    ComposeLoader.add_constructor(tag, compose_value)


def load_configuration(text):
    loader = ComposeLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def main():
    for path in ROOT.rglob("*.yml"):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        load_configuration(path.read_text())
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
