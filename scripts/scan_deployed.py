"""Rescan actual promoted release digests when new vulnerabilities are published."""
import json
import subprocess
from pathlib import Path

from release import validate


def main():
    deployments = json.loads(subprocess.check_output(["gh", "api", "repos/cvn-mosprom/deploy/deployments?per_page=100"], text=True))
    selected = {}
    for deployment in deployments:
        environment = deployment["environment"]
        if environment not in {"staging", "production"} or environment in selected:
            continue
        statuses = json.loads(subprocess.check_output(["gh", "api", f'repos/cvn-mosprom/deploy/deployments/{deployment["id"]}/statuses'], text=True))
        if not statuses or statuses[0]["state"] != "success":
            continue
        payload = deployment.get("payload", {})
        if isinstance(payload, str):
            payload = json.loads(payload)
        selected[environment] = payload["releaseId"]
    for release_id in set(selected.values()):
        data = validate(json.loads((Path("releases") / (release_id + ".json")).read_text()))
        refs = [image["repository"] + "@" + image["digest"] for image in data["images"].values()]
        refs += list(set(data["external"].values()))
        for ref in refs:
            subprocess.run(["trivy", "image", "--severity", "HIGH,CRITICAL", "--exit-code", "1", ref], check=True)


if __name__ == "__main__":
    main()
