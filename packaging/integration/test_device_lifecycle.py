"""The whole device lifecycle against a live hub and a live second machine.

Scan finds a stranger; credentials make it installable; one action delivers
the native package and joins it; forgetting it on the hub makes its agent let
go by itself; a per-device link brings it back; leaving from the device side
empties the hub's record at once. Every transition of the state table in
architecture.md, walked once.

The box is wired here — a router serving the spare port — so nothing depends
on what an earlier test left behind. It needs the lab: a client VM on the
served wire answering SSH with the ``id_lab`` key beside this file, its
``lab`` account holding passwordless sudo. Without those it skips rather
than guessing at somebody's real network.
"""

import subprocess
import time
from pathlib import Path

import pytest

import test_mode_matrix as matrix

ID_LAB = Path(__file__).resolve().parent / "id_lab"
LIFECYCLE_LAN = "192.168.93.1"

CLIENT_TIMEOUT_S = 180
INSTALL_TIMEOUT_S = 240
UNBIND_TIMEOUT_S = 60
LEAVE_TIMEOUT_S = 30
POLL_INTERVAL_S = 3


def wait_for(what, predicate, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"timed out waiting for {what}")


def device_by_mac(panel, mac):
    listed = panel.read("/devices")["devices"]
    return next((entry for entry in listed if entry["mac_address"] == mac), None)


def ssh_to(host, command):
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(ID_LAB),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            f"lab@{host}",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.fixture(scope="module")
def serving(panel, before):
    """A router serving the spare wire, wired by this file itself."""
    if not ID_LAB.is_file():
        pytest.skip("no lab key beside the tests; this walk needs the VM lab")
    physical = [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["link"]["is_present"]
        and entry["settings"]["vlan"] is None
        and entry["link"]["kind"] == "ethernet"
    ]
    spares = [name for name in physical if name != before["interface"]]
    if not spares:
        pytest.skip("this box has no spare port to serve on")
    matrix.put_mode(panel, "router")
    matrix.put_interface(
        panel, spares[-1], role="lan", lan=matrix.lan_body(LIFECYCLE_LAN)
    )
    # Exposure is written as a whole set, never as a side effect of one
    # interface's save; the agent on the served wire needs the panel to
    # answer there.
    exposed = [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"]["is_exposed"]
    ]
    if spares[-1] not in exposed:
        matrix.put_options(panel, exposed_interfaces=exposed + [spares[-1]])
    return spares[-1]


@pytest.fixture(scope="module")
def stranger(panel, serving):
    """The client on the served wire, once its lease and its SSH answer."""

    def scanned_candidate():
        status, listed = panel.call("POST", "/devices/scan")
        assert status == 200
        for entry in listed["devices"]:
            if (
                entry["is_online"]
                and not entry["is_stored"]
                and entry["client"] is None
                and entry["ipv4_address"].startswith(LIFECYCLE_LAN.rsplit(".", 1)[0])
            ):
                return entry
        return None

    candidate = wait_for(
        "the client's lease on the served wire", scanned_candidate, CLIENT_TIMEOUT_S
    )
    probe = ssh_to(candidate["ipv4_address"], "true")
    if probe.returncode != 0:
        pytest.skip("the scanned machine does not answer the lab key")
    return candidate


def test_the_lifecycle_walks_every_transition(panel, stranger):
    mac = stranger["mac_address"]
    host = stranger["ipv4_address"]

    # Credentials make it installable: the lab key becomes a stored key the
    # device references, and the lab account's sudo prompts for nothing.
    status, key = panel.call(
        "POST",
        "/credentials/ssh_keys",
        {"name": "lab key", "private_key": ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "PUT",
        f"/devices/{mac}",
        {
            "name": "lab client",
            "ssh": {
                "host": host,
                "port": 22,
                "username": "lab",
                "auth": "key",
                "key_id": key["id"],
            },
        },
    )
    assert status == 200, saved
    assert saved["is_stored"] is True

    # One action: the native package over SSH, then the same connect a person
    # would run. Managed means the handshake completed — a heartbeat, never a
    # generated token.
    status, started = panel.call(
        "POST", f"/devices/{mac}/action", {"action": "install_client"}
    )
    assert status == 200, started
    wait_for(
        "the installed agent's first heartbeat",
        lambda: (device_by_mac(panel, mac) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )
    managed = device_by_mac(panel, mac)
    assert managed["client"]["is_managed"] is True

    # The hub lets go by deleting the token. The agent is refused, and after
    # a few beats it unbinds by itself and says so on its own machine.
    assert panel.status("DELETE", f"/devices/{mac}") == 200
    wait_for(
        "the refused agent to let go",
        lambda: "joined no gateway" in ssh_to(host, "sudo nagent status").stdout,
        UNBIND_TIMEOUT_S,
    )
    row = device_by_mac(panel, mac)
    assert row is None or row["client"] is None

    # A link generated for this device brings it back through the same enroll
    # path, onto the same MAC-keyed row.
    status, generated = panel.call(
        "POST", "/devices/enrollment", {"name": "lab client", "mac_address": mac}
    )
    assert status == 200, generated
    joined = ssh_to(host, f"sudo nagent connect --yes {generated['link']}")
    assert "joined" in joined.stdout, joined.stdout + joined.stderr
    wait_for(
        "the re-enrolled agent to report",
        lambda: (device_by_mac(panel, mac) or {}).get("is_agent_online"),
        UNBIND_TIMEOUT_S,
    )

    # The device lets go by leaving: the hub's record empties at once, and
    # what the owner typed survives.
    left = ssh_to(host, "sudo nagent disconnect")
    assert "left the hub" in left.stdout, left.stdout + left.stderr
    wait_for(
        "the hub to drop the leaver's token",
        lambda: (device_by_mac(panel, mac) or {"client": None})["client"] is None,
        LEAVE_TIMEOUT_S,
    )
    survivor = device_by_mac(panel, mac)
    assert survivor is not None and survivor["name"] == "lab client"

    # Leave the box as this file found it.
    assert panel.status("DELETE", f"/devices/{mac}") == 200
    panel.call("DELETE", f"/credentials/ssh_keys/{key['id']}")
