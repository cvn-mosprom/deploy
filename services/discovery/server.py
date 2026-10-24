"""Public region catalogue backed by private readiness checks. Standard library only."""
from __future__ import annotations

import concurrent.futures
import json
import os
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

LOCK = threading.Lock()
STATE = {"version": 1, "ttlSeconds": 60, "regions": []}
UPDATED = 0.0


def configuration(path: Path) -> dict:
    config = json.loads(path.read_text())
    zone = config["trustedZone"].lower()
    if not zone or not isinstance(config["regions"], list) or len(config["regions"]) > 16:
        raise ValueError("invalid region configuration")
    seen = set()
    for region in config["regions"]:
        origin = urlsplit(region["apiBaseUrl"])
        if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
                or origin.port or origin.query or origin.fragment or origin.path not in {"", "/"}
                or not (origin.hostname == zone or origin.hostname.endswith("." + zone))):
            raise ValueError("untrusted public origin")
        if region["id"] in seen or region["status"] not in {"ready", "draining", "unavailable"}:
            raise ValueError("duplicate region or invalid status")
        seen.add(region["id"])
        if not region.get("releaseId") or not region.get("compatibleFrontendRevisions"):
            raise ValueError("release metadata missing")
        if not str(region["readyUrl"]).startswith(("http://", "https://")):
            raise ValueError("invalid readiness URL")
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("readiness redirect rejected")


def open_http(url, context):
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("HTTP readiness endpoints only")
    return urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context)).open(url, timeout=1)


def assess(region: dict, context: ssl.SSLContext) -> dict:
    # Internal addresses, credentials and diagnostic errors are never returned publicly.
    public = {key: region[key] for key in ("id", "name", "apiBaseUrl", "status", "apiVersion", "releaseId", "compatibleFrontendRevisions")}
    if public["status"] != "ready":
        return public
    try:
        request = urllib.request.Request(region["readyUrl"], headers={"Accept": "application/json"})
        with open_http(request.full_url, context) as response:
            data = json.load(response)
            if response.status != 200 or data.get("status") != "ready":
                raise ValueError("region not ready")
        ping_url = region["readyUrl"].rsplit("/", 1)[0] + "/routing/ping"
        with open_http(ping_url, context) as response:
            identity = json.load(response)
            if identity.get("regionId") != region["id"] or identity.get("releaseId") != region["releaseId"] or identity.get("apiVersion") != region["apiVersion"]:
                raise ValueError("release metadata mismatch")
    except Exception:
        public["status"] = "unavailable"
    return public


def refresh(path: Path, stop: threading.Event) -> None:
    global STATE, UPDATED
    context = ssl.create_default_context()
    if os.environ.get("DISCOVERY_CA_FILE"):
        context.load_verify_locations(os.environ["DISCOVERY_CA_FILE"])
    if os.environ.get("DISCOVERY_CERT_FILE"):
        context.load_cert_chain(os.environ["DISCOVERY_CERT_FILE"], os.environ["DISCOVERY_KEY_FILE"])
    while not stop.is_set():
        try:
            config = configuration(path)
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                regions = list(pool.map(lambda r: assess(r, context), config["regions"]))
            with LOCK:
                STATE = {"version": 1, "ttlSeconds": 60, "regions": regions}
                UPDATED = time.monotonic()
        except Exception:
            # Fail closed after a bad/missing update, not an eternally healthy cached catalogue.
            with LOCK:
                STATE = {"version": 1, "ttlSeconds": 60, "regions": []}
                UPDATED = 0
        stop.wait(5)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        with LOCK:
            healthy = time.monotonic() - UPDATED < 15
            body = STATE if healthy else {"version": 1, "ttlSeconds": 60, "regions": []}
        if path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            try:
                last_backup = float(Path("/status/backup.timestamp").read_text())
            except (OSError, ValueError):
                last_backup = 0
            try:
                host_metrics = Path("/status/host.prom").read_text()
            except OSError:
                host_metrics = ""
            self.wfile.write((host_metrics + f"mosprom_backup_last_success_timestamp_seconds {last_backup}\n").encode())
            self.wfile.write(f'mosprom_discovery_ready {int(healthy)}\nmosprom_discovery_regions_ready {sum(r["status"] == "ready" for r in body["regions"])}\n'.encode())
            return
        if path == "/ingress-ready":
            region = next((r for r in body["regions"] if r["id"] == os.environ.get("REGION_ID", "local")), None)
            healthy = healthy and region is not None and region["status"] == "ready"
            body = {"status": "ready" if healthy else "unavailable"}
        elif path == "/health":
            body = {"status": "ready" if healthy else "unavailable"}
        elif path != "/routing/regions":
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # No query strings, cookies or user data in access logs.


if __name__ == "__main__":
    stop = threading.Event()
    threading.Thread(target=refresh, args=(Path(os.environ.get("REGIONS_FILE", "/config/regions.json")), stop), daemon=True).start()
    # Internal container network only; Compose never publishes this port.
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # nosec B104
