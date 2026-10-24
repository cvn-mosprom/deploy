"""Run only on a hosted runner; validate gates before dispatching privileged CD."""
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from release import validate


def gh(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def staged(digest: str, release_id: str) -> bool:
    deployments = gh("repos/cvn-mosprom/deploy/deployments?environment=staging&per_page=100")
    for deployment in deployments:
        payload = deployment.get("payload", {})
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload.get("manifestSha256") == digest and payload.get("releaseId") == release_id:
            statuses = gh(f'repos/cvn-mosprom/deploy/deployments/{deployment["id"]}/statuses')
            if statuses and statuses[0]["state"] == "success":
                return True
    return False


def main():
    requested = os.environ.get("REQUESTED_RELEASE", "")
    if requested:
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", requested):
            raise SystemExit("invalid release id")
        path = Path("releases") / (requested + ".json")
    else:
        changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD^", "HEAD", "--", "releases/*.json"], text=True).splitlines()
        if len(changed) != 1:
            raise SystemExit("one complete release manifest per promotion commit required")
        path = Path(changed[0])
    raw = path.read_bytes()
    data = validate(json.loads(raw))
    environment = os.environ["TARGET_ENVIRONMENT"]
    if environment == "production" and not staged(hashlib.sha256(raw).hexdigest(), data["releaseId"]):
        raise SystemExit("exact manifest has no successful staging evidence")
    # No deployment to a privileged runner until current trusted-branch checks are green.
    for _ in range(120):
        checks = gh(f'repos/cvn-mosprom/deploy/commits/{os.environ["GITHUB_SHA"]}/check-runs?per_page=100')["check_runs"]
        states = {item["name"]: item for item in checks if item["name"] in {"validate", "security"}}
        if len(states) == 2 and all(item.get("conclusion") == "success" for item in states.values()):
            break
        if any(item.get("conclusion") in {"failure", "cancelled", "timed_out"} for item in states.values()):
            raise SystemExit("release validation failed")
        time.sleep(5)
    else:
        raise SystemExit("validation did not complete")
    Path("selected.json").write_bytes(raw)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f'release={data["releaseId"]}\nenvironment={environment}\ndeploy-sha={data["deploySha"]}\n')


if __name__ == "__main__":
    main()
