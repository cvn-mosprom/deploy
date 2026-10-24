import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from preflight import read_env

state = Path("/srv/mosprom-staging")
settings = read_env(state / ".env")
release = json.loads((state / "current.json").read_text())
settings["FRONTEND_REVISION"] = release["frontendSha"]
origin = urlsplit(settings["WEBAPP_URL"])
subprocess.run(["python3", "loadtest/run.py", "--base", f"{origin.scheme}://{origin.netloc}", "--profile", os.environ["CAPACITY_PROFILE"],
                "--output", "load-results.json"], env={**os.environ, **settings}, check=True)
