import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

manifest = Path(sys.argv[1]).read_bytes()
data = json.loads(manifest)
state = sys.argv[2]
state_file = Path(os.environ["RUNNER_TEMP"]) / "mosprom-deployment-id"
if state == "in_progress":
    body = {"ref": os.environ["GITHUB_SHA"], "environment": os.environ["TARGET_ENVIRONMENT"], "auto_merge": False,
            "required_contexts": [], "payload": {"releaseId": data["releaseId"], "manifestSha256": hashlib.sha256(manifest).hexdigest()}}
    result = subprocess.check_output(["gh", "api", "-X", "POST", "repos/cvn-mosprom/deploy/deployments", "--input", "-"], input=json.dumps(body), text=True)
    state_file.write_text(str(json.loads(result)["id"]))
deployment_id = state_file.read_text().strip()
subprocess.run(["gh", "api", "-X", "POST", f"repos/cvn-mosprom/deploy/deployments/{deployment_id}/statuses", "--input", "-"],
               input=json.dumps({"state": state, "auto_inactive": False}), text=True, check=True, stdout=subprocess.DEVNULL)
