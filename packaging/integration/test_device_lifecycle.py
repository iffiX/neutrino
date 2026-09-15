"""The whole device lifecycle against a live hub and a live second machine.

Scan finds a stranger; naming it mints the id everything after addresses it
by; one install delivers the native package and joins it over the channel;
forgetting it on the hub is the one refusal that unbinds an agent; a link
brings it back; leaving from the device side empties the hub's binding at
once. Every transition of the state table in protocol.md, walked once.

The box is wired here — a router serving the spare port — so nothing depends
on what an earlier test left behind. It needs the CI/CD pipeline's client VM on the
served wire answering SSH with the ``id_lab`` key beside this file, its
``lab`` account holding passwordless sudo. A missing key fails the walk and
names itself: a lifecycle phase that passes by skipping tested nothing.
"""

import base64
import json
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
DRILL_TIMEOUT_S = 180
POLL_INTERVAL_S = 3

# The agent lives inside the interpreter its package carries; the glob is the
# shell's, so the series in the path is never spelled here.
AGENT_TREE = "/opt/neutrino_agent/python/lib/python3*/site-packages/neutrino_agent"
# The package compiles its bytecode with unchecked hashes, deliberately, so a
# package manager's own mtimes cannot invalidate it. An edit to a source file
# in that tree does nothing until the bytecode beside it is gone, which is
# what the drills below do before they restart the service.
DROP_BYTECODE = f"sudo rm -rf {AGENT_TREE}/__pycache__"


def wait_for(what, predicate, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"timed out waiting for {what}")


def device_by_id(panel, device_id):
    """One device row, by the id the hub minted for it."""
    listed = panel.read("/hub/device")["devices"]
    return next((entry for entry in listed if entry["id"] == device_id), None)


def device_by_mac(panel, mac):
    """The row that holds one address, stored rows before scan rows."""
    listed = panel.read("/hub/device")["devices"]
    return next((entry for entry in listed if mac in entry["mac_addresses"]), None)


# What the running agent says about itself, asked over its control socket.
# It is root's alone, so the probe runs as root; each prints one JSON line,
# and base64 dodges ssh quoting.
CONTROL_STATE_SCRIPT = """
import http.client, json, socket

SOCK = "/run/neutrino_agent/agent.sock"


class SockConn(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost")

    def connect(self):
        s = socket.socket(socket.AF_UNIX)
        s.connect(SOCK)
        self.sock = s


c = SockConn()
c.request("GET", "/api/state")
r = c.getresponse()
state = json.loads(r.read().decode() or "{}")
print(json.dumps({
    "status": r.status,
    "is_connected": state.get("is_connected"),
    "is_online": state.get("is_online"),
    "binding": state.get("binding"),
}))
"""


def client_python(host, script, *, is_root):
    """Run a probe script on the client, as root or as the lab account."""
    encoded = base64.b64encode(script.encode()).decode()
    runner = "sudo python3 -" if is_root else "python3 -"
    return ssh_to(host, f"echo {encoded} | base64 -d | {runner}")


def probe_json(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


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


def patch_protocol(host, number):
    """Make the installed agent claim one protocol number and restart it."""
    return ssh_to(
        host,
        f"sudo sed -i 's/^PROTOCOL = .*/PROTOCOL = {number}/' "
        f"{AGENT_TREE}/constants.py && grep '^PROTOCOL' {AGENT_TREE}/constants.py"
        f" && {DROP_BYTECODE} && sudo systemctl restart neutrino_agent",
    )


def refusal_said(host):
    """What ``nagent status`` says once the hub has turned this agent away.

    Args:
        host: The machine's address.

    Returns:
        The whole of what the command printed, empty until it names a
        protocol refusal.
    """
    said = ssh_to(host, "sudo nagent status").stdout
    return said if "speaks protocol" in said else ""


@pytest.fixture(scope="module")
def serving(panel, before):
    """A router serving the spare wire, wired by this file itself."""
    if not ID_LAB.is_file():
        pytest.fail(
            f"no lab key at {ID_LAB}: push it beside these tests "
            "(vm_exec.py <hub> push <lab>/id_lab /opt/integration/id_lab, "
            "then chmod 600). This walk drives a second machine over SSH and "
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
        panel, spares[-1], role="lan", lan=matrix.lan_body(LIFECYCLE_LAN)
    )
    # Exposure is written as a whole set, never as a side effect of one
    # interface's save; the agent on the served wire needs the panel to
    # answer there.
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
    mac = stranger["link_mac"]
    host = stranger["ipv4_address"]

    # The lab key becomes a stored key, and naming the scan row is what mints
    # the id every call after this one carries.
    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": "lab key", "private_key": ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "POST", "/hub/device/set", {"device_id": stranger["id"], "name": "lab client"}
    )
    assert status == 200, saved
    assert saved["is_stored"] is True
    assert saved["id"] != stranger["id"]
    device_id = saved["id"]

    # One install: the native package over SSH, then the same join a person
    # would run. Managed means the handshake completed — a binding, never a
    # generated token.
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
    wait_for(
        "the installed agent's first heartbeat",
        lambda: (device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )
    managed = device_by_id(panel, device_id)
    assert managed["client"]["is_managed"] is True
    assert managed["machine_id"], managed

    # The control socket is root's alone, and what it answers is the binding
    # the hub just handed out.
    control = probe_json(client_python(host, CONTROL_STATE_SCRIPT, is_root=True))
    assert control["status"] == 200, control
    assert control["is_connected"] is True, control
    assert control["binding"]["id"] == device_id, control
    refused = client_python(host, CONTROL_STATE_SCRIPT, is_root=False)
    assert refused.returncode != 0, refused.stdout

    # The upgrade drill: a machine running older agent code must heal itself.
    # A lower version triggers the self-update, which ends with the real
    # package installed, the service actually restarted and the heartbeat
    # green — exactly the chain that once shipped new code to disk while the
    # old process went on beating.
    healthy = device_by_id(panel, device_id)
    real_version = healthy["client"]["version"]

    # The downgrade is read off the file rather than off the hub: the agent
    # updates itself within seconds of the first beat, and a poller watching
    # for the moment in between loses that race by construction.
    downgraded = ssh_to(
        host,
        "sudo sed -i 's/^AGENT_VERSION = .*/AGENT_VERSION = \"0.0.0\"/' "
        f"{AGENT_TREE}/_version.py && grep '^AGENT_VERSION' {AGENT_TREE}/_version.py"
        f" && {DROP_BYTECODE} && sudo systemctl restart neutrino_agent",
    )
    assert '"0.0.0"' in downgraded.stdout, downgraded.stdout + downgraded.stderr
    # The machine is read before the hub is: the hub goes on reporting the
    # session it still holds for a moment after the agent has gone, so the
    # file the package overwrites is what says the update happened.
    wait_for(
        "the self-update to put the package's own version file back",
        lambda: '"0.0.0"'
        not in ssh_to(host, f"grep '^AGENT_VERSION' {AGENT_TREE}/_version.py").stdout,
        DRILL_TIMEOUT_S,
    )
    wait_for(
        "the updated agent to beat again",
        lambda: (device_by_id(panel, device_id) or {"client": None}).get("client")
        and device_by_id(panel, device_id)["client"]["version"] == real_version
        and device_by_id(panel, device_id)["is_agent_online"],
        DRILL_TIMEOUT_S,
    )

    # A protocol outside the hub's range is turned away at the door, on both
    # sides of it, and the binding is untouched: only a hub that has
    # forgotten this machine unbinds it.
    for number, advice in ((0, "update this agent"), (2, "update the hub")):
        patched = patch_protocol(host, number)
        assert f"PROTOCOL = {number}" in patched.stdout, patched.stdout + patched.stderr
        told = wait_for(
            f"the agent to report the protocol {number} refusal",
            lambda: refusal_said(host),
            UNBIND_TIMEOUT_S,
        )
        assert advice in told, told
        assert "joined no gateway" not in told, told

    restored = patch_protocol(host, 1)
    assert "PROTOCOL = 1" in restored.stdout, restored.stdout + restored.stderr
    wait_for(
        "the agent speaking the hub's protocol again",
        lambda: (device_by_id(panel, device_id) or {}).get("is_agent_online"),
        DRILL_TIMEOUT_S,
    )

    # The hub lets go by removing the row. The agent is refused with the one
    # code that unbinds it, and says so on its own machine. It has a backoff
    # to sit out first, so this waits a drill's worth rather than a beat's.
    assert panel.status("POST", "/hub/device/remove", {"device_id": device_id}) == 200
    wait_for(
        "the refused agent to let go",
        lambda: "joined no gateway" in ssh_to(host, "sudo nagent status").stdout,
        DRILL_TIMEOUT_S,
    )
    assert device_by_id(panel, device_id) is None

    # A fresh link brings the machine back through the same join, onto a row
    # of its own, carrying the name the link was made with.
    status, generated = panel.call(
        "POST", "/hub/device/enrollment/create", {"name": "lab client"}
    )
    assert status == 200, generated
    joined = ssh_to(host, f"sudo nagent join --yes {generated['link']}")
    assert "joined" in joined.stdout, joined.stdout + joined.stderr
    rejoined = wait_for(
        "the re-enrolled agent to report",
        lambda: (device_by_mac(panel, mac) or {}).get("is_agent_online")
        and device_by_mac(panel, mac),
        UNBIND_TIMEOUT_S,
    )
    device_id = rejoined["id"]
    assert rejoined["name"] == "lab client"

    # The device lets go by leaving: the hub's binding empties at once, and
    # what the owner typed survives.
    left = ssh_to(host, "sudo nagent leave")
    assert "left the hub" in left.stdout, left.stdout + left.stderr
    wait_for(
        "the hub to drop the leaver's binding",
        lambda: (device_by_id(panel, device_id) or {"client": None})["client"] is None,
        LEAVE_TIMEOUT_S,
    )
    survivor = device_by_id(panel, device_id)
    assert survivor is not None and survivor["name"] == "lab client"

    # Leave the box as this file found it.
    assert panel.status("POST", "/hub/device/remove", {"device_id": device_id}) == 200
    panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})
