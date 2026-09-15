"""Every operation the Devices page offers, and the edges around them.

A device is an id the hub mints, and the only way a row comes into being
without an agent joining is a scan row being named. The addresses here are
QEMU's own prefix and belong to no machine on any network this runs on: what
is checked is the register, never a device answering.
"""

import pytest

DEVICE_MAC = "52:54:00:aa:bb:cc"
DEVICE_SCAN_ID = f"scan:{DEVICE_MAC}"
# A second address, so the row this file forgets is never the one the module
# fixture is still holding.
LEAVER_MAC = "52:54:00:aa:bb:cd"
# More devices than a LAN this size holds, added and then forgotten.
CROWD_SIZE = 50


def devices(panel) -> list:
    """Every device the box knows about."""
    return panel.read("/hub/device")["devices"]


def crowd(panel) -> list:
    """The devices this file added. A device the box discovered by scanning has
    no name at all, so the name is read as one it may not have."""
    return [
        entry for entry in devices(panel) if (entry["name"] or "").startswith("crowd")
    ]


def stored_with(panel, mac_address: str) -> list:
    """The stored rows that hold one address."""
    return [
        entry
        for entry in devices(panel)
        if entry["is_stored"] and mac_address in entry["mac_addresses"]
    ]


def adopt(panel, scan_id: str, name: str) -> dict:
    """Name a scan row, which is what stores it under an id of its own."""
    status, device = panel.call(
        "POST", "/hub/device/set", {"device_id": scan_id, "name": name}
    )
    assert status == 200, device
    return device


@pytest.fixture(scope="module")
def registered(panel):
    """A box with one device in its register, by the id the hub minted."""
    device = adopt(panel, DEVICE_SCAN_ID, "audit")
    yield device["id"]
    panel.call("POST", "/hub/device/remove", {"device_id": device["id"]})


def test_naming_a_scan_row_stores_it_under_an_id_of_its_own(registered, panel):
    """The scan id is where the row was found, never what it is called after."""
    stored = stored_with(panel, DEVICE_MAC)

    assert len(stored) == 1
    assert stored[0]["id"] == registered
    assert stored[0]["id"] != DEVICE_SCAN_ID
    assert stored[0]["is_stored"] is True


def test_a_device_is_renamed_by_its_id(registered, panel):
    assert (
        panel.status(
            "POST", "/hub/device/set", {"device_id": registered, "name": "renamed"}
        )
        == 200
    )

    stored = stored_with(panel, DEVICE_MAC)
    assert len(stored) == 1
    assert stored[0]["name"] == "renamed"


@pytest.mark.parametrize(
    "device_id", ["hello", "scan:52:54:00:aa:bb", "00000000000000000000000000000000"]
)
def test_an_id_that_is_no_device_is_a_404(panel, device_id):
    body = {"device_id": device_id, "name": "no"}

    assert panel.status("POST", "/hub/device/set", body) == 404


def test_an_ssh_key_that_is_not_stored_is_refused(registered, panel):
    body = {
        "device_id": registered,
        "ssh": {"host": "10.0.0.5", "username": "me", "key_id": "nosuchkey"},
    }

    assert panel.status("POST", "/hub/device/set", body) == 400


def test_installing_the_agent_with_no_credential_is_refused(registered, panel):
    """Reported as the refusal it is, rather than minutes later as a task that
    could never have connected."""
    body = {"device_id": registered, "host": "192.0.2.9", "username": "itest"}

    assert panel.status("POST", "/hub/device/agent/install", body) == 400


def test_a_device_with_no_agent_has_none_online(registered, panel):
    modules = panel.read(f"/agent/module?device_id={registered}")

    assert modules["is_agent_online"] is False


def test_a_crowd_of_devices_is_added_and_forgotten(panel):
    made = [
        adopt(
            panel,
            f"scan:52:54:00:00:{index // 16:02x}:{index % 16:02x}",
            f"crowd{index}",
        )["id"]
        for index in range(CROWD_SIZE)
    ]
    assert len(made) == CROWD_SIZE

    added = crowd(panel)
    assert len(added) == CROWD_SIZE

    gone = sum(
        panel.status("POST", "/hub/device/remove", {"device_id": entry["id"]}) == 200
        for entry in added
    )
    assert gone == CROWD_SIZE
    assert crowd(panel) == []


def test_a_device_is_forgotten(panel):
    device = adopt(panel, f"scan:{LEAVER_MAC}", "leaver")

    assert (
        panel.status("POST", "/hub/device/remove", {"device_id": device["id"]}) == 200
    )
    assert stored_with(panel, LEAVER_MAC) == []
