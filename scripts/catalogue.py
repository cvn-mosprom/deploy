#!/usr/bin/env python3
"""Atomic catalogue updates preserve each node's actual release during a rolling update."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--drain")
    action.add_argument("--activate")
    parser.add_argument("--release")
    parser.add_argument("--frontend")
    args = parser.parse_args()
    data = json.loads(args.path.read_text())
    found = False
    for region in data["regions"]:
        if region["id"] == (args.drain or args.activate):
            found = True
            region["status"] = "draining" if args.drain else "ready"
            if args.activate:
                if not args.release or not args.frontend:
                    raise SystemExit("release coordinates required")
                region.update(releaseId=args.release, compatibleFrontendRevisions=[args.frontend])
    if not found:
        raise SystemExit("unknown region")
    temporary = args.path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.path)


if __name__ == "__main__":
    main()
