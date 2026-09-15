"""The channel end to end: pinned TLS from the link to the heartbeat.

The link carries the certificate's fingerprint, the channel's own port and
the role it was made for, and its addresses are the exposed ones, because
exposure is the only thing that opens a port on a network. A good fingerprint
joins and beats; a tampered one is refused on the device before the ticket is
sent.

It needs the lab: a client VM on the served wire answering SSH with the
``id_lab`` key beside this file, its ``lab`` account holding passwordless
sudo. A missing key fails the walk and names itself: a lifecycle phase that
passes by skipping tested nothing.
"""

import base64
import json
import urllib.parse

import pytest

import test_device_lifecycle as lifecycle
import test_mode_matrix as matrix

CHANNEL_LAN = "192.168.94.1"
WRONG_FINGERPRINT = "0" * 64

CLIENT_TIMEOUT_S = 180
INSTALL_TIMEOUT_S = 240
LEAVE_TIMEOUT_S = 30


def tampered(link: str) -> str:
    """The same link with its fingerprint replaced, everything else intact."""
    payload = generated_payload(link)
    payload["fp"] = WRONG_FINGERPRINT
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def generated_payload(link: str) -> dict:
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


@pytest.fixture(scope="module")
def serving(panel, before):
    """A router serving the spare wire, with the wire exposed."""
    if not lifecycle.ID_LAB.is_file():
        pytest.fail(
            f"no lab key at {lifecycle.ID_LAB}: push it beside these tests "
            "(vm_exec.py <hub> push <lab>/id_lab /opt/integration/id_lab, "
            "then chmod 600). This walk enrolls a second machine over SSH and "
            "cannot pass without one."
        )
    physical = [
        entry["settings"]["name"]
        for entry in panel.read("/hub/network")["interfaces"]
        if entry["link"]["is_present"]
        and entry["settings"]["vlan"] is None
        and entry["link"]["kind"] == "ethernet"
    ]
    spares = [name for name in physical if name != before["interface"]]
    if not spares:
        pytest.skip("this box has no spare port to serve on")
    matrix.put_mode(panel, "router")
    # The way in becomes the way out, whatever role an earlier file left
    # on it: a router with no uplink serves a network with nothing behind
    # it, and the machine on it cannot reach a package archive.
    matrix.put_interface(panel, before["interface"], role="wan")
    matrix.put_interface(
        panel, spares[-1], role="lan", lan=matrix.lan_body(CHANNEL_LAN)
    )
    # Exposure is what opens the channel's port on a network, so the wire
    # the second machine joins from is in the set.
    exposed = [
        entry["settings"]["name"]
        for entry in panel.read("/hub/network")["interfaces"]
        if entry["settings"]["is_exposed"]
    ]
    if spares[-1] not in exposed:
        matrix.put_options(panel, exposed_interfaces=exposed + [spares[-1]])
    return spares[-1]


@pytest.fixture(scope="module")
def stranger(panel, serving):
    """The client on the served wire, once its lease and its SSH answer."""

    def scanned_candidate():
        status, listed = panel.call("POST", "/hub/device/scan")
        assert status == 200
        for entry in listed["devices"]:
            if (
                entry["is_online"]
                and not entry["is_stored"]
                and entry["client"] is None
                and entry["ipv4_address"].startswith(CHANNEL_LAN.rsplit(".", 1)[0])
            ):
                return entry
        return None

    candidate = lifecycle.wait_for(
        "the client's lease on the served wire", scanned_candidate, CLIENT_TIMEOUT_S
    )
    probe = lifecycle.ssh_to(candidate["ipv4_address"], "true")
    if probe.returncode != 0:
        pytest.skip("the scanned machine does not answer the lab key")
    return candidate


def test_the_channel_is_pinned_tls_end_to_end(panel, stranger):
    host = stranger["ipv4_address"]

    # The link names the channel: TLS on every exposed address, the role it
    # was made for, and the fingerprint the device will hold the socket to.
    status, generated = panel.call(
        "POST", "/hub/device/enrollment/create", {"name": ""}
    )
    assert status == 200, generated
    payload = generated_payload(generated["link"])
    assert payload["urls"], payload
    assert all(url.startswith("https://") for url in payload["urls"])
    assert payload["role"] == "agent", payload
    assert len(payload["fp"]) == 64 and int(payload["fp"], 16) >= 0
    # The served wire is exposed, so its own address is one of them, and the
    # port is the channel's rather than the panel's.
    assert any(url.startswith(f"https://{CHANNEL_LAN}:") for url in payload["urls"])
    panel_port = urllib.parse.urlsplit(panel.base_url).port or 80
    assert all(urllib.parse.urlsplit(url).port != panel_port for url in payload["urls"])

    # The install delivers the agent and joins through that channel; the
    # first heartbeat is the proof the pinned TLS port answers on the served
    # wire.
    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": "channel lab key", "private_key": lifecycle.ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "POST", "/hub/device/set", {"device_id": stranger["id"], "name": "tls client"}
    )
    assert status == 200, saved
    device_id = saved["id"]
    status, started = panel.call(
        "POST",
        "/hub/device/agent/install",
        {
            "device_id": device_id,
            "host": host,
            "port": 22,
            "username": "lab",
            "key_id": key["id"],
        },
    )
    assert status == 200, started
    lifecycle.wait_for(
        "the installed agent's first heartbeat over TLS",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )

    # Unbind from the device side, so the refusals below are the link's alone.
    left = lifecycle.ssh_to(host, "sudo nagent leave")
    assert "left the hub" in left.stdout, left.stdout + left.stderr
    lifecycle.wait_for(
        "the hub to drop the leaver's binding",
        lambda: (lifecycle.device_by_id(panel, device_id) or {"client": None})["client"]
        is None,
        LEAVE_TIMEOUT_S,
    )

    # A wrong-fingerprint link is refused on the device, visibly, with the
    # ticket never sent.
    status, fresh = panel.call(
        "POST",
        "/hub/device/enrollment/create",
        {"device_id": device_id, "name": "tls client"},
    )
    assert status == 200, fresh
    refused = lifecycle.ssh_to(
        host, f"sudo nagent join --yes {tampered(fresh['link'])}"
    )
    assert refused.returncode != 0
    assert "certificate" in refused.stdout + refused.stderr
    row = lifecycle.device_by_id(panel, device_id)
    assert row is None or row["client"] is None

    # The untampered link joins, and the heartbeat flows again.
    joined = lifecycle.ssh_to(host, f"sudo nagent join --yes {fresh['link']}")
    assert "joined" in joined.stdout, joined.stdout + joined.stderr
    lifecycle.wait_for(
        "the re-enrolled agent to report",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )

    # Leave the box as this file found it.
    lifecycle.ssh_to(host, "sudo nagent leave")
    assert panel.status("POST", "/hub/device/remove", {"device_id": device_id}) == 200
    panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})
