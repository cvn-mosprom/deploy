#!/usr/bin/env python3
"""Measured game workload, using isolated test users and no Telegram sends."""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import random
import statistics
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx


def init_data(token, user_id):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id, "first_name": "e2e-load"}, separators=(",", ":"))}
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    payload = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def main_async(args):
    durations, statuses = [], []
    stop = time.monotonic() + args.duration
    base_id = 10**12 + random.randrange(10**9)

    async def player(index):
        headers = {"X-Telegram-Init-Data": init_data(os.environ["BOT_TOKEN"], base_id + index),
                   "X-Frontend-Revision": os.environ["FRONTEND_REVISION"]}
        async with httpx.AsyncClient(base_url=args.base, headers=headers, timeout=10, follow_redirects=False) as client:
            initial = await client.get("/api/bootstrap")
            initial.raise_for_status()
            counter = 0
            while time.monotonic() < stop:
                started = time.monotonic()
                try:
                    if counter % 3:
                        response = await client.get("/api/factory/me")
                    else:
                        response = await client.post("/api/advance", json={"cap_hours": 8, "reason": "heartbeat"})
                    statuses.append(response.status_code)
                    durations.append(time.monotonic() - started)
                except httpx.HTTPError:
                    statuses.append(0)
                    durations.append(time.monotonic() - started)
                counter += 1
                # Stay within the game's per-user rate limits; scale distinct users for throughput.
                await asyncio.sleep(2)

    started = time.monotonic()
    await asyncio.gather(*(player(i) for i in range(args.users)))
    elapsed = time.monotonic() - started
    samples = sorted(durations)
    errors = sum(status == 0 or status >= 500 for status in statuses)
    result = {"users": args.users, "durationSeconds": elapsed, "requests": len(samples), "rps": len(samples) / elapsed,
              "p50Seconds": statistics.median(samples), "p95Seconds": samples[min(len(samples) - 1, int(len(samples) * .95))],
              "serverErrors": errors, "rateLimited": statuses.count(429), "profile": args.profile}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if errors or statuses.count(429):
        raise SystemExit("errors/rate limiting invalidate capacity comparison")
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        if result["p95Seconds"] > baseline["p95Seconds"] * 1.2 or result["rps"] < baseline["rps"] * .95:
            raise SystemExit("performance regression exceeds baseline tolerance")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--profile", default="reference")
    parser.add_argument("--output", type=Path, default=Path("load-results.json"))
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if not args.base.startswith("https://") or args.users < 1 or args.duration < 10:
        raise SystemExit("HTTPS, positive users and duration >= 10 seconds required")
    asyncio.run(main_async(args))
