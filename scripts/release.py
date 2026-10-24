#!/usr/bin/env python3
"""Validate immutable release coordinates and render Compose image variables."""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from pathlib import Path

OWN = {"api", "bot", "sim", "web"}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
REF = re.compile(r"^[a-z0-9][a-z0-9./:_-]+@sha256:[0-9a-f]{64}$")


def validate(data: dict) -> dict:
    if data.get("version") != 1 or not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", data.get("releaseId", "")):
        raise ValueError("invalid release version/id")
    for key in ("backendSha", "frontendSha", "deploySha"):
        if not SHA.fullmatch(data.get(key, "")):
            raise ValueError(f"{key} must be a complete commit SHA")
    if set(data.get("images", {})) != OWN:
        raise ValueError("release must contain exactly api/bot/sim/web")
    for name, image in data["images"].items():
        if image.get("repository") != f"ghcr.io/cvn-mosprom/{name}" or not DIGEST.fullmatch(image.get("digest", "")):
            raise ValueError(f"invalid {name} coordinate")
        if image.get("sourceSha") != data["backendSha"] or image.get("frontendSha") != data["frontendSha"]:
            raise ValueError("mixed source revisions")
    required = {"postgres", "redis", "discovery", "haproxy", "pgbouncer", "prometheus", "grafana", "alertmanager", "pgbackrest", "etcd", "patroni"}
    if not required <= set(data.get("external", {})):
        raise ValueError("external image set incomplete")
    for name, reference in data["external"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or not REF.fullmatch(reference):
            raise ValueError(f"external {name} must be digest-pinned")
    compatibility = data.get("schemaCompatibility", {})
    if not isinstance(compatibility.get("rollbackSafe"), bool):
        raise ValueError("schemaCompatibility.rollbackSafe must be explicit")
    if not data.get("routingZone") or not re.fullmatch(r"[a-z0-9.-]+", data["routingZone"]):
        raise ValueError("routingZone required")
    return data


def verify(data: dict, issuer: str = "https://token.actions.githubusercontent.com") -> None:
    for name, image in data["images"].items():
        ref = f'{image["repository"]}@{image["digest"]}'
        identity = "https://github.com/cvn-mosprom/backend/.github/workflows/ci.yml@refs/heads/main"
        subprocess.run(["cosign", "verify", "--certificate-identity", identity, "--certificate-oidc-issuer", issuer, ref], check=True, stdout=subprocess.DEVNULL)
        attested = subprocess.check_output(["cosign", "verify-attestation", "--type", "slsaprovenance1", "--certificate-identity", identity,
                                           "--certificate-oidc-issuer", issuer, ref], text=True)
        envelopes = []
        rest = attested.strip()
        decoder = json.JSONDecoder()
        while rest:
            item, consumed = decoder.raw_decode(rest)
            envelopes.extend(item if isinstance(item, list) else [item])
            rest = rest[consumed:].lstrip()
        expected = {"backendSha": data["backendSha"], "frontendSha": data["frontendSha"]}
        if not any(json.loads(base64.b64decode(e["payload"]))["predicate"].get("buildDefinition", {}).get("externalParameters", {}).get("mospromSource") == expected for e in envelopes):
            raise ValueError("signed provenance does not match release sources")
        platforms = json.loads(subprocess.check_output(["docker", "buildx", "imagetools", "inspect", ref, "--raw"], text=True))
        if not any(m.get("platform", {}).get("architecture") == "amd64" and m.get("platform", {}).get("os") == "linux" for m in platforms.get("manifests", [])):
            raise ValueError("linux/amd64 image missing")
    for name in ("discovery", "patroni", "pgbackrest"):
        identity = "https://github.com/cvn-mosprom/deploy/.github/workflows/infrastructure-images.yml@refs/heads/main"
        subprocess.run(["cosign", "verify", "--certificate-identity", identity, "--certificate-oidc-issuer", issuer, data["external"][name]], check=True, stdout=subprocess.DEVNULL)


def render(data: dict) -> str:
    out = [f'RELEASE_ID={data["releaseId"]}', f'FRONTEND_REVISION={data["frontendSha"]}', f'ROUTING_ZONE={data["routingZone"]}']
    out += [f'{name.upper()}_IMAGE={image["repository"]}@{image["digest"]}' for name, image in sorted(data["images"].items())]
    out += [f'{name.upper()}_IMAGE={ref}' for name, ref in sorted(data["external"].items())]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    data = validate(json.loads(args.manifest.read_text()))
    if args.verify:
        verify(data)
    if args.render:
        print(render(data), end="")


if __name__ == "__main__":
    main()
