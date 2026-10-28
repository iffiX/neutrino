"""The channel end to end: the link, the knock and the handshake, the heartbeat.

The link carries the hub's static key, the agent port and the role it was
made for, and its addresses are the exposed ones, because exposure is the
only thing that opens a port on a network. A link with the hub's key joins
and beats; a link with another key meets silence and spends no ticket. A
binding of 0.5 on the device reads as one until the device joins again, and
a connection that opens with TLS, as a peer of 0.5 does, gets no byte and
then a reset.

It needs the lab: a client VM on the served wire answering SSH with the
``id_lab`` key beside this file, its ``lab`` account holding passwordless
sudo. A missing key fails the walk and names itself: a lifecycle phase that
passes by skipping tested nothing.
"""

import base64
import json
import socket
import ssl
import time
import urllib.parse
import zlib

import pytest

import test_device_lifecycle as lifecycle
import test_mode_matrix as matrix

CHANNEL_LAN = "192.168.94.1"
# The hub's static public key, and the panel's settings naming the agent port.
HUB_PUBLIC_KEY_PATH = "/etc/neutrino/hub/transport/public_key"
PANEL_SETTINGS_PATH = "/etc/neutrino/hub/web/settings.json"
AGENT_PORT_DEFAULT = 8443
# The binding file of the agent on the client.
AGENT_BINDING_PATH = "/etc/neutrino/agent/agent.json"
# A binding an agent of 0.5 left: a certificate fingerprint and no hub key.
LEGACY_BINDING = {
    "gateway_url": f"https://{CHANNEL_LAN}:8443",
    "id": "legacy",
    "token": "t" * 32,
    "fingerprint": "f" * 64,
    "machine_id": "",
}
LEGACY_WORDS = "this binding is from 0.5"
LEGACY_ADVICE = "run nagent join with a new link"
# How long the agent port holds a refused connection before its reset, a
# deadline drawn from 5 to 30 seconds after the accept.
DOOR_HOLD_MIN_S = 5
DOOR_HOLD_MAX_S = 30
DOOR_HOLD_SLACK_S = 5

CLIENT_TIMEOUT_S = 180
# The first install on a fresh client runs its first `apt-get update`, which
# fetches the full package lists: about four minutes in the lab.
FIRST_INSTALL_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 240
LEAVE_TIMEOUT_S = 30
LEGACY_TIMEOUT_S = 60


def tampered(link: str) -> str:
    """The same link with another hub key, everything else intact."""
    payload = generated_payload(link)
    payload["key"] = "%064x" % (int(payload["key"], 16) ^ 1)
    text = json.dumps(payload, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(zlib.compress(text, 9)).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def generated_payload(link: str) -> dict:
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(padded)))


def hub_public_key() -> str:
    """The hub's static public key, as the transport wrote it."""
    with open(HUB_PUBLIC_KEY_PATH, encoding="utf-8") as stream:
        return stream.read().strip()


def agent_port() -> int:
    """The agent port the panel's settings name."""
    try:
        with open(PANEL_SETTINGS_PATH, encoding="utf-8") as stream:
            settings = json.load(stream)
    except (OSError, ValueError):
        settings = {}
    return int(settings.get("agent_listen_port", AGENT_PORT_DEFAULT))


def tls_client_hello() -> bytes:
    """The first bytes a TLS client writes, as a peer of 0.5 opens with."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    outgoing = ssl.MemoryBIO()
    connection = context.wrap_bio(ssl.MemoryBIO(), outgoing)
    try:
        connection.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return outgoing.read()


def write_legacy_binding(host: str):
    """Leave a binding of 0.5 on the client and restart its agent."""
    encoded = base64.b64encode(json.dumps(LEGACY_BINDING).encode()).decode()
    return lifecycle.ssh_to(
        host,
        f"echo {encoded} | base64 -d | sudo tee {AGENT_BINDING_PATH} >/dev/null"
        f" && sudo chmod 600 {AGENT_BINDING_PATH}"
        " && sudo systemctl restart neutrino_agent",
    )


def legacy_status(host: str) -> str:
    """What ``nagent status`` prints, empty until it words a binding of 0.5."""
    said = lifecycle.ssh_to(host, "sudo nagent status").stdout
    return said if LEGACY_WORDS in said else ""


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
        if entry["settings"]["is_ipv4_exposed"]
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


def test_a_tls_hello_gets_no_byte_and_then_a_reset(panel):
    with socket.create_connection(("127.0.0.1", agent_port()), timeout=10) as sock:
        sock.settimeout(DOOR_HOLD_MAX_S + DOOR_HOLD_SLACK_S)
        started = time.monotonic()
        sock.sendall(tls_client_hello())
        try:
            answer = sock.recv(1)
        except ConnectionResetError:
            answer = None
        held_s = time.monotonic() - started

    assert answer is None, answer
    assert DOOR_HOLD_MIN_S - 1 <= held_s <= DOOR_HOLD_MAX_S + DOOR_HOLD_SLACK_S


def test_the_channel_runs_through_the_transport_end_to_end(panel, stranger):
    host = stranger["ipv4_address"]

    # The link names the channel: the agent port on every exposed address,
    # the role it was made for, and the hub's static key.
    status, generated = panel.call(
        "POST", "/hub/device/enrollment/create", {"name": ""}
    )
    assert status == 200, generated
    payload = generated_payload(generated["link"])
    assert payload["urls"], payload
    assert all(url.startswith("tcp://") for url in payload["urls"])
    assert payload["role"] == "agent", payload
    assert payload["key"] == hub_public_key()
    assert "fp" not in payload
    # The served wire is exposed, so its own address is one of them, and the
    # port is the channel's rather than the panel's.
    assert any(url.startswith(f"tcp://{CHANNEL_LAN}:") for url in payload["urls"])
    panel_port = urllib.parse.urlsplit(panel.base_url).port or 80
    assert all(urllib.parse.urlsplit(url).port != panel_port for url in payload["urls"])

    # The install delivers the agent and joins through the transport; the
    # first heartbeat is the proof the agent port admits it on the served
    # wire.
    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": "channel lab key", "private_key": lifecycle.ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "POST",
        "/hub/device/set",
        {"device_id": stranger["id"], "name": "channel client"},
    )
    assert status == 200, saved
    device_id = saved["id"]
    try:
        walk_the_channel(panel, host=host, device_id=device_id, key_id=key["id"])
    finally:
        # Leave the box as this file found it, a failed walk too: a stored
        # device is one the later walks no longer accept as the stranger.
        lifecycle.ssh_to(host, "sudo nagent leave --yes")
        panel.call("POST", "/hub/device/remove", {"device_id": device_id})
        panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})


def walk_the_channel(panel, *, host: str, device_id: str, key_id: str) -> None:
    """Install, leave, a link of another key, a binding of 0.5, and a rejoin."""
    status, started = panel.call(
        "POST",
        "/hub/device/agent/install",
        {
            "device_id": device_id,
            "host": host,
            "port": 22,
            "username": "lab",
            "key_id": key_id,
        },
    )
    assert status == 200, started
    lifecycle.wait_for(
        "the installed agent's first heartbeat through the transport",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        FIRST_INSTALL_TIMEOUT_S,
    )

    # Unbind from the device side, so the refusals below are the link's alone.
    left = lifecycle.ssh_to(host, "sudo nagent leave --yes")
    assert "left the hub" in left.stdout, left.stdout + left.stderr
    lifecycle.wait_for(
        "the hub to drop the leaver's binding",
        lambda: (lifecycle.device_by_id(panel, device_id) or {"client": None})["client"]
        is None,
        LEAVE_TIMEOUT_S,
    )

    # A link of another key knocks with another magic. The agent port sends
    # nothing back, the join fails on the device, and the ticket stays open.
    status, fresh = panel.call(
        "POST",
        "/hub/device/enrollment/create",
        {"device_id": device_id, "name": "channel client"},
    )
    assert status == 200, fresh
    refused = lifecycle.ssh_to(
        host, f"sudo nagent join --yes {tampered(fresh['link'])}"
    )
    assert refused.returncode != 0, refused.stdout + refused.stderr
    assert "hub_unreachable" in refused.stdout + refused.stderr
    assert "joined no hub" in lifecycle.ssh_to(host, "sudo nagent status").stdout
    row = lifecycle.device_by_id(panel, device_id)
    assert row is None or row["client"] is None

    # A binding of 0.5 holds no hub key. The agent dials nothing, and its
    # status names the join that binds the machine again.
    written = write_legacy_binding(host)
    assert written.returncode == 0, written.stdout + written.stderr
    said = lifecycle.wait_for(
        "the agent to word its binding of 0.5",
        lambda: legacy_status(host),
        LEGACY_TIMEOUT_S,
    )
    assert LEGACY_ADVICE in said, said
    assert "service    running" in said, said

    # The link of the hub's key joins over the binding of 0.5, on the ticket
    # the other key left unspent, and the heartbeat flows again.
    joined = lifecycle.ssh_to(host, f"sudo nagent join --yes {fresh['link']}")
    assert "joined" in joined.stdout, joined.stdout + joined.stderr
    lifecycle.wait_for(
        "the re-enrolled agent to report",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )
