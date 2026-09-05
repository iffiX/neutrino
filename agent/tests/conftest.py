"""Suite-wide isolation: no test touches the machine's own service state."""

import pytest

import neutrino_agent.services.mounts as mounts_module
import neutrino_agent.services.store as store_module


@pytest.fixture(autouse=True)
def _isolated_service_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store_module, "AGENT_SERVICE_STORE_PATH", str(tmp_path / "services.json")
    )
    monkeypatch.setattr(
        mounts_module,
        "AGENT_MOUNT_CREDENTIALS_DIR",
        str(tmp_path / "mount_credentials"),
    )
