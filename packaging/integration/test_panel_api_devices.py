"""Every operation the Devices page offers, and the edges around them.

The addresses here are QEMU's own prefix and belong to no machine on any
network this runs on: what is checked is the register, never a device
answering.
"""

import pytest

DEVICE_MAC = "52:54:00:aa:bb:cc"
# More devices than a LAN this size holds, added and then forgotten.
CROWD_SIZE = 50


def devices(panel) -> list:
    """Every device the box knows about."""
    return panel.read("/devices")["devices"]


def crowd(panel) -> list:
    """The devices this file added. A device the box discovered by scanning has
    no name at all, so the name is read as one it may not have."""
    return [
        entry for entry in devices(panel) if (entry["name"] or "").startswith("crowd")
    ]


def named(panel, mac_address: str) -> list:
    """The records held for one address."""
    return [entry for entry in devices(panel) if entry["mac_address"] == mac_address]


@pytest.fixture(scope="module")
def registered(panel):
    """A box with one device in its register."""
    assert panel.status("PUT", f"/devices/{DEVICE_MAC}", {"name": "audit"}) == 200
    yield panel
    panel.call("DELETE", f"/devices/{DEVICE_MAC}")


def test_adding_the_same_address_again_renames_it(registered, panel):
    """There is no second record to make: the address is the identity."""
    assert panel.status("PUT", f"/devices/{DEVICE_MAC}", {"name": "renamed"}) == 200

    stored = named(panel, DEVICE_MAC)
    assert len(stored) == 1
    assert stored[0]["name"] == "renamed"


def test_the_same_address_in_capitals_is_the_same_device(registered, panel):
    assert (
        panel.status("PUT", f"/devices/{DEVICE_MAC.upper()}", {"name": "shouting"})
        == 200
    )
    assert len(named(panel, DEVICE_MAC)) == 1


@pytest.mark.parametrize("address", ["hello", "52:54:00:aa:bb", "52:54:00:aa:bb:cc:dd"])
def test_an_address_that_is_not_a_mac_is_refused(panel, address):
    assert panel.status("PUT", f"/devices/{address}", {"name": "no"}) == 400


def test_an_ssh_key_that_is_not_stored_is_refused(registered, panel):
    body = {"ssh": {"host": "10.0.0.5", "username": "me", "key_id": "nosuchkey"}}

    assert panel.status("PUT", f"/devices/{DEVICE_MAC}", body) == 400


def test_an_action_that_is_not_one_is_refused(registered, panel):
    assert (
        panel.status("POST", f"/devices/{DEVICE_MAC}/action", {"action": "sing"}) == 400
    )


def test_installing_the_agent_with_no_credentials_is_a_conflict(registered, panel):
    """Reported as the refusal it is, rather than minutes later as a task that
    could never have connected."""
    body = {"action": "install_client"}

    assert panel.status("POST", f"/devices/{DEVICE_MAC}/action", body) == 409


def test_a_device_with_no_agent_has_none_online(registered, panel):
    modules = panel.read(f"/devices/{DEVICE_MAC}/modules")

    assert modules["is_agent_online"] is False


def test_a_crowd_of_devices_is_added_and_forgotten(panel):
    made = sum(
        panel.status(
            "PUT",
            f"/devices/52:54:00:00:{index // 16:02x}:{index % 16:02x}",
            {"name": f"crowd{index}"},
        )
        == 200
        for index in range(CROWD_SIZE)
    )
    assert made == CROWD_SIZE

    added = crowd(panel)
    assert len(added) == CROWD_SIZE

    gone = sum(
        panel.status("DELETE", f"/devices/{entry['mac_address']}") == 200
        for entry in added
    )
    assert gone == CROWD_SIZE
    assert crowd(panel) == []


def test_a_device_is_forgotten(panel):
    assert panel.status("PUT", f"/devices/{DEVICE_MAC}", {"name": "audit"}) == 200

    assert panel.status("DELETE", f"/devices/{DEVICE_MAC}") == 200
    assert named(panel, DEVICE_MAC) == []
