"""The agent channel end to end: pinned TLS from the link to the heartbeat.

The link carries the certificate's fingerprint and the agent channel's own
port; the wire it is used on is served but deliberately not exposed, because
the channel answers on every served network. A good fingerprint enrolls and
beats; a tampered one is refused on the device before anything is sent.

It needs the lab: a client VM on the served wire answering SSH with the
``id_lab`` key beside this file, its ``lab`` account holding passwordless
sudo. A missing key fails the walk and names itself: a lifecycle phase that
passes by skipping tested nothing.
"""

import base64
import json

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
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    payload["fp"] = WRONG_FINGERPRINT
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def generated_payload(link: str) -> dict:
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


@pytest.fixture(scope="module")
def serving(panel, before):
    """A router serving the spare wire, and the wire left unexposed."""
    if not lifecycle.ID_LAB.is_file():
        pytest.fail(
            f"no lab key at {lifecycle.ID_LAB}: push it beside these tests "
            "(vm_exec.py <hub> push <lab>/id_lab /opt/integration/id_lab, "
            "then chmod 600). This walk enrolls a second machine over SSH and "
            "cannot pass without one."
        )
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
        panel, spares[-1], role="lan", lan=matrix.lan_body(CHANNEL_LAN)
    )
    # Deliberately unexposed: the agent channel must answer on a served wire
    # the panel does not.
    exposed = [
        entry["settings"]["name"]
        for entry in panel.read("/network")["interfaces"]
        if entry["settings"]["is_exposed"]
    ]
    if spares[-1] in exposed:
        exposed.remove(spares[-1])
        matrix.put_options(panel, exposed_interfaces=exposed)
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
    mac = stranger["mac_address"]
    host = stranger["ipv4_address"]

    # The link names the agent channel: TLS on every served address, and the
    # fingerprint the device will hold the socket to.
    status, generated = panel.call("POST", "/devices/enrollment", {"name": ""})
    assert status == 200, generated
    payload = generated_payload(generated["link"])
    assert payload["urls"], payload
    assert all(url.startswith("https://") for url in payload["urls"])
    assert len(payload["fp"]) == 64 and int(payload["fp"], 16) >= 0

    # The install delivers the agent and joins through that channel; the
    # first heartbeat is the proof the pinned TLS port answers on the
    # unexposed served wire.
    status, key = panel.call(
        "POST",
        "/credentials/ssh_keys",
        {"name": "channel lab key", "private_key": lifecycle.ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "PUT",
        f"/devices/{mac}",
        {
            "name": "tls client",
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
    status, started = panel.call(
        "POST", f"/devices/{mac}/action", {"action": "install_client"}
    )
    assert status == 200, started
    lifecycle.wait_for(
        "the installed agent's first heartbeat over TLS",
        lambda: (lifecycle.device_by_mac(panel, mac) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )

    # The package endpoint answers over the same pinned channel with the same
    # token, and the bytes match the digest the reply names — the transport a
    # self-updating agent trusts. Run with the device's own installed agent
    # code, as an update would.
    script = (
        "import hashlib; "
        "from neutrino_agent.core import enrollment; "
        "from neutrino_agent.constants import AGENT_PACKAGE_PATH; "
        "from neutrino_agent.core.channel import GatewayHttpChannel; "
        "from neutrino_agent.platforms.detect import platform_tuple; "
        "from neutrino_agent.core.self_update import package_kind; "
        "config = enrollment.load_config(); "
        'channel = GatewayHttpChannel(gateway_url=config["gateway_url"], '
        'token=config["token"], fingerprint=config.get("fingerprint", "")); '
        "machine = platform_tuple(); "
        "kind = package_kind(machine); "
        "named = channel.post_download(AGENT_PACKAGE_PATH, "
        '{"family": kind, "architecture": machine["arch"]}, '
        '"/tmp/hub_agent_package"); '
        'data = open("/tmp/hub_agent_package", "rb").read(); '
        "matched = named == hashlib.sha256(data).hexdigest(); "
        'print(kind, "digest-ok" if matched else "digest-bad", len(data))'
    )
    # The interpreter the package carries, which is the only one the agent
    # is importable from.
    agent_python = "/opt/neutrino_agent/python/bin/python3"
    fetched = lifecycle.ssh_to(host, f"sudo {agent_python} -c '{script}'")
    assert fetched.returncode == 0, fetched.stdout + fetched.stderr
    kind, verdict, size = fetched.stdout.split()
    assert kind in ("deb", "rpm")
    assert verdict == "digest-ok"
    assert int(size) > 10 * 1024

    # Unbind from the device side, so the refusals below are the link's alone.
    left = lifecycle.ssh_to(host, "sudo nagent disconnect")
    assert "left the hub" in left.stdout, left.stdout + left.stderr
    lifecycle.wait_for(
        "the hub to drop the leaver's token",
        lambda: (lifecycle.device_by_mac(panel, mac) or {"client": None})["client"]
        is None,
        LEAVE_TIMEOUT_S,
    )

    # A wrong-fingerprint link is refused on the device, visibly, with the
    # ticket never sent.
    status, fresh = panel.call(
        "POST", "/devices/enrollment", {"name": "tls client", "mac_address": mac}
    )
    assert status == 200, fresh
    refused = lifecycle.ssh_to(
        host, f"sudo nagent connect --yes {tampered(fresh['link'])}"
    )
    assert refused.returncode != 0
    assert "certificate" in refused.stdout + refused.stderr
    row = lifecycle.device_by_mac(panel, mac)
    assert row is None or row["client"] is None

    # The untampered link joins, and the heartbeat flows again.
    joined = lifecycle.ssh_to(host, f"sudo nagent connect --yes {fresh['link']}")
    assert "joined" in joined.stdout, joined.stdout + joined.stderr
    lifecycle.wait_for(
        "the re-enrolled agent to report",
        lambda: (lifecycle.device_by_mac(panel, mac) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )

    # Leave the box as this file found it.
    lifecycle.ssh_to(host, "sudo nagent disconnect")
    assert panel.status("DELETE", f"/devices/{mac}") == 200
    panel.call("DELETE", f"/credentials/ssh_keys/{key['id']}")
