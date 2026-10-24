#!/usr/bin/env python3
"""Host-side collection: no Docker socket or privileged mounts in monitoring containers."""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state", type=Path)
    parser.add_argument("--environment", choices=["staging", "production"], required=True)
    args = parser.parse_args()
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    values = {"mosprom_node_memory_available_bytes": memory["MemAvailable"], "mosprom_node_memory_total_bytes": memory["MemTotal"],
              "mosprom_node_cpu_count": os.cpu_count(), "mosprom_node_load1": os.getloadavg()[0],
              "mosprom_node_disk_free_bytes": shutil.disk_usage(args.state).free}
    output = [f"{name} {value}" for name, value in values.items()]
    for project in ["mosprom-" + args.environment, "mosprom-" + args.environment + "-ha"]:
        containers = subprocess.check_output(["docker", "ps", "--filter", "label=com.docker.compose.project=" + project,
                                              "--format", '{{.ID}} {{.Label "com.docker.compose.service"}}'], text=True).splitlines()
        for line in containers:
            container, service = line.split()
            if not re.fullmatch(r"[a-z0-9-]{1,32}", service):
                continue
            stats = json.loads(subprocess.check_output(["docker", "stats", "--no-stream", "--format", "{{json .}}", container], text=True))
            for metric, key in [("cpu_ratio", "CPUPerc"), ("memory_ratio", "MemPerc")]:
                value = float(stats[key].rstrip("%")) / 100
                output.append(f'mosprom_container_{metric}{{service="{service}"}} {value}')
    folder = args.state / "monitoring"
    folder.mkdir(mode=0o750, exist_ok=True)
    temporary = folder / "host.prom.tmp"
    temporary.write_text("\n".join(output) + "\n")
    temporary.replace(folder / "host.prom")


if __name__ == "__main__":
    main()
