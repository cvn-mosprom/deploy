import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate import load_configuration


def test_compose_merge_tags_preserve_config_types():
    data = load_configuration("ports: !override [127.0.0.1:8080:80]\nreset: !reset []\nsettings: !override {enabled: true}\nvalue: !reset null\n")
    assert data == {"ports": ["127.0.0.1:8080:80"], "reset": [], "settings": {"enabled": True}, "value": None}


@pytest.mark.parametrize("payload", ["!unexpected example", "!!python/object/apply:os.system ['exit 1']"])
def test_configuration_rejects_unknown_or_executable_tags(payload):
    with pytest.raises(yaml.constructor.ConstructorError):
        load_configuration(payload)
