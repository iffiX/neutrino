"""An SSH server instance is published with the fingerprint of its account's
key, read from the sealed key in ``ssh_server.json``; a rotated key gives a
new fingerprint."""

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.services.published import PublishedServiceCache
from tests.conftest import unlock_vault


@pytest.fixture
def states(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    held = DesiredStateStore()
    held.write("d1", "accounts", {"accounts": [{"account": "lab"}]})
    held.set_enabled_accounts("d1", "ssh_server", ["lab"])
    return held


def test_each_instance_carries_its_account_keys_fingerprint(states):
    cache = PublishedServiceCache(
        declared_probe=None, served_models=None, units=None, desired_states=states
    )
    status = {
        "details": {
            "host_key_fingerprint": "SHA256:host",
            "instances": [{"account": "lab", "port": 22001, "is_running": True}],
        }
    }

    first = cache._hosted_ssh_server("d1", status)
    fingerprint = first["instances"][0]["account_key_fingerprint"]
    assert fingerprint == states.account_key_fingerprint("d1", "lab")
    states.rotate_account_secret("d1", "ssh_server", "lab", "private_key_sealed")
    second = cache._hosted_ssh_server("d1", status)

    assert fingerprint.startswith("SHA256:") and len(fingerprint) == 50
    assert second["instances"][0]["account_key_fingerprint"] != fingerprint
