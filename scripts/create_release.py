#!/usr/bin/env python3
"""Assemble all four CI image results atomically. Never mixes build runs."""
import argparse
import json
from pathlib import Path

from release import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--deploy-sha", required=True)
    parser.add_argument("--routing-zone", required=True)
    parser.add_argument("--infra", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    images = {}
    source = frontend = None
    for path in args.artifacts.rglob("image.json"):
        result = json.loads(path.read_text())
        if result["name"] in images:
            raise ValueError("duplicate image")
        source = source or result["sourceSha"]
        frontend = frontend or result["frontendSha"]
        if result["sourceSha"] != source or result["frontendSha"] != frontend:
            raise ValueError("mixed CI builds")
        images[result["name"]] = {key: result[key] for key in ("repository", "digest", "sourceSha", "frontendSha")}
    infrastructure = json.loads(args.infra.read_text())
    data = {"version": 1, "releaseId": source, "backendSha": source, "frontendSha": frontend,
            "deploySha": args.deploy_sha, "routingZone": args.routing_zone, "images": images,
            "external": {**json.loads((Path(__file__).resolve().parents[1] / "images.lock.json").read_text()), **infrastructure},
            # Conservatively require explicit review before enabling automatic rollback.
            "schemaCompatibility": {"rollbackSafe": False}}
    validate(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main()
