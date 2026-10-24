import importlib.util
import json
import ssl
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("discovery", Path(__file__).resolve().parents[1] / "services/discovery/server.py")
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


def region():
    return {"id": "kzn", "name": "КАЗАНЬ", "apiBaseUrl": "https://kzn.game.example.com", "readyUrl": "https://kzn.game.example.com/ready",
            "status": "ready", "apiVersion": 1, "releaseId": "release-1", "compatibleFrontendRevisions": ["sha"]}


def test_internal_addresses_and_diagnostic_errors_are_never_exposed():
    data = region()
    data["readyUrl"] = "http://private.internal:8000/ready"
    with patch.object(discovery, "open_http", side_effect=ConnectionError("secret internal endpoint")):
        public = discovery.assess(data, ssl.create_default_context())
    assert public["status"] == "unavailable"
    assert "readyUrl" not in public
    assert "private" not in json.dumps(public)


def test_drained_regions_do_not_receive_health_traffic():
    data = region()
    data["status"] = "draining"
    with patch.object(discovery, "open_http", side_effect=AssertionError("must not probe")):
        assert discovery.assess(data, ssl.create_default_context())["status"] == "draining"


@pytest.mark.parametrize("origin", ["http://kzn.game.example.com", "https://game.example.com.evil.org", "https://u:p@kzn.game.example.com", "https://kzn.game.example.com:8443"])
def test_config_rejects_untrusted_origins(tmp_path, origin):
    data = region()
    data["apiBaseUrl"] = origin
    path = tmp_path / "regions.json"
    path.write_text(json.dumps({"trustedZone": "game.example.com", "regions": [data]}))
    with pytest.raises(ValueError):
        discovery.configuration(path)


def test_configuration_requires_unique_regions_and_compatible_release(tmp_path):
    data = region()
    path = tmp_path / "regions.json"
    path.write_text(json.dumps({"trustedZone": "game.example.com", "regions": [data, data]}))
    with pytest.raises(ValueError):
        discovery.configuration(path)
