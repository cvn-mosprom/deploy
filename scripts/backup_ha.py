#!/usr/bin/env python3
"""Run on every HA node; only the verified primary backs up to encrypted S3."""
import argparse
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from preflight import read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state", type=Path)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    env = read_env(args.state / ".env")
    context = ssl.create_default_context(cafile=str(args.state / "tls/ca.crt"))
    context.load_cert_chain(str(args.state / "tls/patroni.crt"), str(args.state / "tls/patroni.key"))
    try:
        # WG_IP is validated/provisioned inventory data, never a request parameter.
        with urllib.request.urlopen("https://" + env["WG_IP"] + ":8008/primary", context=context, timeout=3) as response:  # nosec B310
            if response.status != 200:
                return
    except urllib.error.HTTPError as error:
        if error.code == 503:
            return
        raise
    subprocess.run(["docker", "compose", "--env-file", str(args.state / "images.env"), "-f", str(args.state / "ha/compose.yml"),
                    "exec", "-T", "patroni", "pgbackrest", "--stanza=mosprom", "--type=" + ("full" if args.full else "diff"), "backup"], check=True)
    folder = args.state / "monitoring"
    folder.mkdir(mode=0o750, exist_ok=True)
    (folder / "backup.timestamp").write_text(str(time.time()))


if __name__ == "__main__":
    main()
