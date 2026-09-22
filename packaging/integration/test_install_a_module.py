"""Installing a module on a managed machine the way the Modules page does.

Its own file because it is the one check here that takes minutes and changes
a second machine: everything in `test_panel_api_modules.py` reads the list and
the refusals around it, deliberately installing nothing.

That gap is why a real failure reached a person before it reached a test. What
the panel writes is a want; what makes it true is the device's own package
manager, run by the agent's unit, with the lines coming back up the channel.
Nothing that only reads the page can see that chain break — it takes an
install, through the panel, on a machine with a package manager.

`samba` is the module used, and deliberately: the platform carries it, so the
install is the machine's own package manager reaching its own archive, which
is the shape every other platform-tier module has.

The same managed machine answers the checks that need an agent on the socket:
a configuration saved through the panel is checked on the machine and read
back as written, and the unit's journal comes back up the channel. Beside
them sits the one refusal shape a write with no body gets.

It needs the same second machine the lifecycle walk does: a client VM on the
served wire answering SSH with the ``id_lab`` key beside this file.
"""

import pytest

import test_device_lifecycle as lifecycle
import test_mode_matrix as matrix

MODULE = "samba"
MODULE_LAN = "192.168.95.1"
# One share, every field spelled, so the read-back is compared whole.
SHARE = {
    "name": "integration",
    "path": "/srv/integration",
    "comment": "saved through the panel",
    "is_read_only": True,
    "valid_users": [],
}
JOURNAL_LINES = 50

CLIENT_TIMEOUT_S = 180
INSTALL_TIMEOUT_S = 600


def modules_of(panel, device_id) -> dict:
    """The device's module rows, by name."""
    view = panel.read(f"/agent/module?device_id={device_id}")
    return {entry["name"]: entry for entry in view["modules"]}


def row_of(panel, device_id) -> dict:
    """The one module this file walks."""
    rows = modules_of(panel, device_id)
    assert MODULE in rows, sorted(rows)
    return rows[MODULE]


def wait_state(panel, device_id, wanted, states) -> dict:
    """Wait until the hub asks for ``wanted`` and the machine reports one of
    ``states``, which is both surfaces agreeing."""

    def settled():
        row = row_of(panel, device_id)
        return row if row["want"] == wanted and row["state"] in states else None

    return lifecycle.wait_for(
        f"{MODULE} to read {wanted} on the hub and {states} on the machine",
        settled,
        INSTALL_TIMEOUT_S,
    )


@pytest.fixture(scope="module")
def serving(panel, before):
    """A router serving the spare wire, wired by this file itself."""
    if not lifecycle.ID_LAB.is_file():
        pytest.fail(
            f"no lab key at {lifecycle.ID_LAB}: push it beside these tests "
            "(vm_exec.py <hub> push <lab>/id_lab /opt/integration/id_lab, "
            "then chmod 600). This walk installs on a second machine and "
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
    matrix.put_interface(panel, spares[-1], role="lan", lan=matrix.lan_body(MODULE_LAN))
    exposed = [
        entry["settings"]["name"]
        for entry in panel.read("/hub/network")["interfaces"]
        if entry["settings"]["is_exposed"]
    ]
    if spares[-1] not in exposed:
        matrix.put_options(panel, exposed_interfaces=exposed + [spares[-1]])
    return spares[-1]


@pytest.fixture(scope="module")
def managed(panel, serving):
    """The second machine, joined to this hub, and let go again afterwards."""

    def scanned_candidate():
        status, listed = panel.call("POST", "/hub/device/scan")
        assert status == 200
        for entry in listed["devices"]:
            if (
                entry["is_online"]
                and not entry["is_stored"]
                and entry["client"] is None
                and entry["ipv4_address"].startswith(MODULE_LAN.rsplit(".", 1)[0])
            ):
                return entry
        return None

    candidate = lifecycle.wait_for(
        "the client's lease on the served wire", scanned_candidate, CLIENT_TIMEOUT_S
    )
    host = candidate["ipv4_address"]
    if lifecycle.ssh_to(host, "true").returncode != 0:
        pytest.skip("the scanned machine does not answer the lab key")

    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": "module lab key", "private_key": lifecycle.ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "POST",
        "/hub/device/set",
        {"device_id": candidate["id"], "name": "module client"},
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
        "the installed agent's first heartbeat",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )
    yield device_id
    lifecycle.ssh_to(host, "sudo nagent leave")
    panel.call("POST", "/hub/device/remove", {"device_id": device_id})
    panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})


@pytest.fixture(scope="module")
def installed(panel, managed):
    """The module, installed through the panel and watched to its state."""
    row = row_of(panel, managed)
    if not row["is_supported"]:
        pytest.skip(f"{MODULE} is not offered on this machine")
    if row["state"] != "absent":
        pytest.skip(f"{MODULE} already reads {row['state']} on this machine")

    status, answer = panel.call(
        "POST", "/agent/module/install", {"device_id": managed, "module": MODULE}
    )
    assert status == 200, answer
    return wait_state(panel, managed, "installed", ("installed", "stopped", "running"))


def test_the_module_is_installed_afterwards(installed):
    """Not "the want was written": a want a machine cannot satisfy is written
    just as easily. What the page says about the module is the only answer
    that matters to the person who pressed the button."""
    assert installed["state"] != "failed", installed
    assert installed["want"] == "installed"


def test_the_machine_says_why_when_it_can(installed):
    """A row that installed carries no failure code; one that failed carries
    the machine's own words rather than only that something went wrong."""
    assert installed["code"] == "", installed


def test_a_saved_share_list_reads_back_as_it_was_written(panel, managed, installed):
    """The save is checked by the machine's own `testparm`, stored under the
    device and pushed; the page then reads the same shares back, whole."""
    status, answer = panel.call(
        "POST",
        "/agent/module/samba/share/set",
        {"device_id": managed, "shares": [SHARE]},
    )
    assert status == 200, answer
    assert answer["shares"] == [SHARE], answer

    view = panel.read(f"/agent/module/samba?device_id={managed}")
    assert view["shares"] == [SHARE], view


def test_starting_it_makes_the_machine_run_it(panel, managed, installed):
    status, answer = panel.call(
        "POST", "/agent/module/start", {"device_id": managed, "module": MODULE}
    )
    assert status == 200, answer

    row = wait_state(panel, managed, "running", ("running",))
    assert row["is_active"] is True, row


def test_the_modules_journal_comes_back_from_the_machine(panel, managed, installed):
    """The unit has started by now, so its journal has lines: the route runs
    `journalctl` on the device over the channel and returns the tail."""
    path = (
        f"/agent/module/journal?device_id={managed}"
        f"&module={MODULE}&lines={JOURNAL_LINES}"
    )

    view = panel.read(path)

    lines = view["text"].splitlines()
    assert lines, view
    assert len(lines) <= JOURNAL_LINES


def test_stopping_it_leaves_it_installed(panel, managed, installed):
    status, answer = panel.call(
        "POST", "/agent/module/stop", {"device_id": managed, "module": MODULE}
    )
    assert status == 200, answer

    row = wait_state(panel, managed, "stopped", ("stopped",))
    assert row["is_active"] is False, row


def test_the_page_offers_to_uninstall_what_is_installed(panel, managed, installed):
    """The other half of the button, and the state the next install starts
    from. The machine's data stays; only the package goes."""
    status, answer = panel.call(
        "POST", "/agent/module/uninstall", {"device_id": managed, "module": MODULE}
    )
    assert status == 200, answer

    assert wait_state(panel, managed, "absent", ("absent",))["state"] == "absent"


def test_a_write_with_no_body_is_refused_in_the_one_shape(panel):
    """Sent with no body at all where the route wants an object. The answer
    is the panel's `{code, params}` with `body_invalid`, never FastAPI's own
    422 list."""
    status, answer = panel.call("POST", "/hub/proxy/node/test")

    assert status == 400, answer
    assert answer["detail"]["code"] == "body_invalid", answer
