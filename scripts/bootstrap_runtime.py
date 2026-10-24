#!/usr/bin/env python3
"""Create runtime metadata from a release and inventory; never fabricate release digests."""
import argparse
import json
from pathlib import Path

import yaml

from release import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = validate(json.loads(args.manifest.read_text()))
    inventory = yaml.safe_load(args.inventory.read_text())
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    regions = []
    for host in inventory["all"]["children"]["mosprom"]["hosts"].values():
        regions.append({"id": host["region_id"], "name": host["region_name"], "apiBaseUrl": host["public_origin"],
                        "readyUrl": host["readiness_url"], "status": host.get("routing_status", "ready"), "apiVersion": 1,
                        "releaseId": data["releaseId"], "compatibleFrontendRevisions": [data["frontendSha"]]})
    (args.output / "monitoring").mkdir(mode=0o755, exist_ok=True)
    (args.output / "routing").mkdir(mode=0o755, exist_ok=True)
    (args.output / "routing/regions.json").write_text(json.dumps({"trustedZone": data["routingZone"], "regions": regions}, ensure_ascii=False, indent=2) + "\n")
    targets = [{"targets": [host["wg_ip"] + ":8008"], "labels": {"__scheme__": "https", "__metrics_path__": "/metrics", "region": host["region_id"]}}
               for host in inventory["all"]["children"]["mosprom"]["hosts"].values() if host.get("wg_ip")]
    for host in inventory["all"]["children"]["mosprom"]["hosts"].values():
        if host.get("wg_ip"):
            for metrics_path, role in [("/metrics", "api"), ("/discovery-metrics", "discovery")]:
                targets.append({"targets": [host["wg_ip"] + ":9443"], "labels": {"__scheme__": "http", "__metrics_path__": metrics_path, "region": host["region_id"], "role": role}})
    (args.output / "prometheus-targets.json").write_text(json.dumps(targets) + "\n")


if __name__ == "__main__":
    main()
