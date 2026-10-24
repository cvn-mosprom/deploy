import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from release import render, validate
from preflight import check


def manifest():
    return {"version": 1, "releaseId": "release-1", "backendSha": "a" * 40, "frontendSha": "b" * 40,
            "deploySha": "c" * 40, "routingZone": "game.example.com", "schemaCompatibility": {"rollbackSafe": False},
            "images": {name: {"repository": f"ghcr.io/cvn-mosprom/{name}", "digest": "sha256:" + "d" * 64,
                              "sourceSha": "a" * 40, "frontendSha": "b" * 40} for name in ("api", "bot", "sim", "web")},
            "external": {name: "example.org/image@sha256:" + "e" * 64 for name in ("postgres", "redis", "discovery", "haproxy", "pgbouncer", "prometheus", "grafana", "alertmanager", "pgbackrest", "etcd", "patroni")}}


def test_complete_release_renders_only_immutable_images():
    data = validate(manifest())
    output = render(data)
    assert "API_IMAGE=ghcr.io/cvn-mosprom/api@sha256:" in output
    assert "FRONTEND_REVISION=" + "b" * 40 in output


@pytest.mark.parametrize("mutation", [
    lambda m: m["images"].pop("bot"),
    lambda m: m["images"]["sim"].update(frontendSha="f" * 40),
    lambda m: m["images"]["api"].update(repository="evil.org/api"),
    lambda m: m["external"].update(redis="redis:latest"),
    lambda m: m.update(deploySha="main"),
    lambda m: m.update(releaseId="../../etc/passwd"),
    lambda m: m.pop("schemaCompatibility"),
])
def test_invalid_or_mixed_release_fails_closed(mutation):
    data = manifest()
    mutation(data)
    with pytest.raises(ValueError):
        validate(data)


def test_demo_environment_is_rejected():
    assert check({"APP_ENV": "prod", "POSTGRES_USER": "postgres", "DEV_AUTH": "1"})


def test_invalid_signature_blocks_release_before_delivery():
    import subprocess
    from unittest.mock import patch
    from release import verify
    with patch('release.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'cosign')) as checked:
        with pytest.raises(subprocess.CalledProcessError):
            verify(manifest())
    args = checked.call_args.args[0]
    assert args[:2] == ['cosign', 'verify']
    assert 'https://github.com/cvn-mosprom/backend/.github/workflows/ci.yml@refs/heads/main' in args
    assert args[-1].endswith('@sha256:' + 'd' * 64)


def test_valid_signature_with_wrong_source_provenance_is_rejected():
    import base64
    from unittest.mock import patch
    from release import verify
    wrong = {'predicate': {'mospromSource': {'backendSha': 'f' * 40, 'frontendSha': 'b' * 40}}}
    envelope = json.dumps({'payload': base64.b64encode(json.dumps(wrong).encode()).decode()})
    with patch('release.subprocess.run'), patch('release.subprocess.check_output', return_value=envelope):
        with pytest.raises(ValueError, match='sources'):
            verify(manifest())


def test_signed_image_must_support_target_platform():
    import base64
    from unittest.mock import patch
    from release import verify
    source = {'predicate': {'buildDefinition': {'externalParameters': {'mospromSource': {'backendSha': 'a' * 40, 'frontendSha': 'b' * 40}}}}}
    envelope = json.dumps({'payload': base64.b64encode(json.dumps(source).encode()).decode()})
    with patch('release.subprocess.run'), patch('release.subprocess.check_output', side_effect=[envelope, '{"manifests": []}']):
        with pytest.raises(ValueError, match='amd64'):
            verify(manifest())


def test_deployment_readiness_uses_origin_when_game_is_under_app():
    from unittest.mock import MagicMock, patch
    from deploy import smoke
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'{"status":"ready"}'
    opener = MagicMock()
    opener.open.return_value = response
    with patch('deploy.urllib.request.build_opener', return_value=opener):
        smoke('https://game.example.com/app?src=telegram')
    opener.open.assert_called_once_with('https://game.example.com/ready', timeout=5)
