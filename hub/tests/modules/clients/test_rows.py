"""The rows the fine mode lists under each kind: an app under each kind of
its entries in the Services page's order, a machine's SSH server, a Home
share each, a folder share once for all its accounts, a desktop and a
managed machine, each with the machine that provides it."""

import pytest

from neutrino_hub.modules.clients.rows import permission_rows
from neutrino_hub.modules.devices.registry import DeviceRegistry


def entry(entry_id, kind, *, app_id="", device_id="d1", source="module", **payload):
    return {
        "id": entry_id,
        "type": kind,
        "title": entry_id,
        "app_id": app_id,
        "device_id": device_id,
        "source": source,
        "payload": payload,
    }


class PublishedServices:
    def __init__(self, entries, apps):
        self.listed = entries
        self.listed_apps = apps

    def entries(self):
        return list(self.listed), "f"

    def apps(self):
        return list(self.listed_apps)


class Runtime:
    def __init__(self, entries, apps):
        self.published_services = PublishedServices(entries, apps)
        self.device_address = {}

    def device_names(self):
        return {device.id: device.name for device in DeviceRegistry().all_stored()}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr("neutrino_hub.modules.clients.services.machine_id", str)
    return tmp_path


def test_each_kind_lists_its_rows_with_their_machine(config):
    device = DeviceRegistry().create("lab", machine_id="m1")
    d1 = device.id
    apps = [
        {"id": f"vscode_{d1}_lab", "title": "VS Code (lab)", "source": "module"},
        {"id": f"gitea_{d1}", "title": "Gitea", "source": "module"},
        {"id": "nas", "title": "NAS", "source": "declared"},
        {"id": f"ssh_server_{d1}", "title": "SSH", "source": "module"},
    ]
    entries = [
        entry(f"vscode_{d1}_lab_web", "web", app_id=f"vscode_{d1}_lab", device_id=d1),
        entry(f"gitea_{d1}_web", "web", app_id=f"gitea_{d1}", device_id=d1),
        entry(f"gitea_{d1}_ssh", "port", app_id=f"gitea_{d1}", device_id=d1),
        entry("nas_web", "web", app_id="nas", device_id="", source="declared"),
        entry("nas_files", "file", app_id="nas", device_id="", source="declared"),
        entry(f"ssh_server_{d1}_lab", "ssh", app_id=f"ssh_server_{d1}", device_id=d1),
        entry(f"ssh_server_{d1}_bob", "ssh", app_id=f"ssh_server_{d1}", device_id=d1),
        entry(f"samba_{d1}_lab", "file", device_id=d1, share="lab"),
        entry(
            f"samba_folder_{d1}_data_lab",
            "file",
            device_id=d1,
            share="data",
            account="lab",
        ),
        entry(
            f"samba_folder_{d1}_data_bob",
            "file",
            device_id=d1,
            share="data",
            account="bob",
        ),
        entry(f"rdp_{d1}", "rdp", device_id=d1),
        entry("ai", "ai", device_id=""),
    ]

    rows = permission_rows(Runtime(entries, apps))

    def ids(kind):
        return [row["id"] for row in rows[kind]]

    assert ids("web") == [f"gitea_{d1}", f"vscode_{d1}_lab", "nas"]
    assert ids("port") == [f"gitea_{d1}"]
    assert ids("ssh") == [f"ssh_server_{d1}"]
    assert ids("file") == ["nas", f"samba_folder_{d1}_data", f"samba_{d1}_lab"]
    assert ids("rdp") == [f"rdp_{d1}"]
    assert ids("terminal") == []
    assert "ai" not in rows and "overlay" not in rows and "panel" not in rows
    assert rows["web"][0] == {
        "id": f"gitea_{d1}",
        "title": "Gitea",
        "device_id": d1,
        "device_name": "lab",
    }
    assert rows["web"][2]["device_id"] == ""
    assert rows["file"][1]["title"] == "data"


def test_a_managed_machine_is_a_terminal_row(config):
    registry = DeviceRegistry()
    device = registry.create("lab", machine_id="m1")
    registry.issue_token(device.id)

    rows = permission_rows(Runtime([], []))

    assert rows["terminal"] == [
        {
            "id": f"terminal_{device.id}",
            "title": "lab",
            "device_id": device.id,
            "device_name": "lab",
        }
    ]
