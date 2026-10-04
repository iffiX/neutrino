"""What removing the agent's package takes from a managed machine, and what
an install after it finds.

The rule is agent.md's: removing the agent takes away what it added in order
to run and to fence, and leaves what the machine serves. A unit named the way
the modules name theirs stands for every module's unit, and one named the way
the hub names its own must stay. The file share is the module whose shares
must survive: its share is still served after the removal, and an install
after it reports that share once, not twice.

It needs the same second machine the module walk does: a client VM on the
served wire answering SSH with the ``id_lab`` key beside this file.
"""

import pytest

import test_device_lifecycle as lifecycle
import test_install_a_module as module_walk
from test_install_a_module import serving  # noqa: F401

SHARE = {
    "name": "removal",
    "path": "/srv/removal",
    "comment": "left by the removal",
    "is_read_only": False,
    "valid_users": [],
}
# A unit named as a module names its units, which the removal takes, and
# one named as the hub names its own, which it leaves.
ADDED_TEMPLATE = "neutrino_removal_check@.service"
ADDED_INSTANCE = "neutrino_removal_check@lab.service"
FOREIGN_UNIT = "neutrino_hub_removal_check.service"
UNIT_DIR = "/etc/systemd/system"
PLANT_UNITS = (
    f"printf '[Service]\\nExecStart=/bin/sleep infinity\\n"
    f"[Install]\\nWantedBy=multi-user.target\\n' "
    f"| sudo tee {UNIT_DIR}/{ADDED_TEMPLATE} {UNIT_DIR}/{FOREIGN_UNIT} >/dev/null"
    f" && sudo systemctl daemon-reload"
    f" && sudo systemctl enable --now {ADDED_INSTANCE}"
)
REMOVE_PACKAGE = (
    "if command -v apt-get >/dev/null; then "
    "sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y neutrino-agent; "
    "else sudo dnf remove -y neutrino-agent; fi"
)
# The SMB server's unit on Debian and on Fedora.
SMB_UNITS = "smbd smb"

INSTALL_TIMEOUT_S = 600


def share_count(host) -> int:
    """How many times the machine's Samba serves the share."""
    shown = lifecycle.ssh_to(host, "sudo testparm -s 2>/dev/null")
    return shown.stdout.count(f"[{SHARE['name']}]")


def install_agent(panel, device_id, host, key_id) -> None:
    """Install the agent on the machine through the panel and wait for it."""
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
        "the installed agent's first heartbeat",
        lambda: (lifecycle.device_by_id(panel, device_id) or {}).get("is_agent_online"),
        INSTALL_TIMEOUT_S,
    )


@pytest.fixture(scope="module")
def machine(panel, serving):  # noqa: F811
    """The second machine, joined, with the file share running one share."""
    candidate = lifecycle.wait_for(
        "the client's lease on the served wire",
        lambda: next(
            (
                entry
                for entry in panel.call("POST", "/hub/device/scan")[1]["devices"]
                if entry["is_online"]
                and not entry["is_stored"]
                and entry["client"] is None
                and entry["ipv4_address"].startswith(
                    module_walk.MODULE_LAN.rsplit(".", 1)[0]
                )
            ),
            None,
        ),
        module_walk.CLIENT_TIMEOUT_S,
    )
    host = candidate["ipv4_address"]
    if lifecycle.ssh_to(host, "true").returncode != 0:
        pytest.skip("the scanned machine does not answer the lab key")
    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": "removal lab key", "private_key": lifecycle.ID_LAB.read_text()},
    )
    assert status == 200, key
    status, saved = panel.call(
        "POST",
        "/hub/device/set",
        {"device_id": candidate["id"], "name": "removal client"},
    )
    assert status == 200, saved
    device_id = saved["id"]
    install_agent(panel, device_id, host, key["id"])

    for path, body in (
        ("/agent/module/install", {"module": "samba"}),
        ("/agent/module/samba/share/set", {"shares": [SHARE]}),
        ("/agent/module/start", {"module": "samba"}),
    ):
        status, answer = panel.call("POST", path, {"device_id": device_id, **body})
        assert status == 200, (path, answer)
        if path == "/agent/module/install":
            module_walk.wait_state(
                panel, device_id, "installed", ("installed", "stopped", "running")
            )
    module_walk.wait_state(panel, device_id, "running", ("running",))
    planted = lifecycle.ssh_to(host, PLANT_UNITS)
    assert planted.returncode == 0, planted.stdout + planted.stderr

    yield {"device_id": device_id, "host": host, "key_id": key["id"]}
    lifecycle.ssh_to(host, f"sudo rm -f {UNIT_DIR}/{FOREIGN_UNIT}")
    lifecycle.ssh_to(host, "sudo nagent leave")
    panel.call("POST", "/hub/device/remove", {"device_id": device_id})
    panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})


@pytest.fixture(scope="module")
def removed(machine):
    """The machine after its agent package was removed."""
    host = machine["host"]
    assert share_count(host) == 1
    result = lifecycle.ssh_to(host, REMOVE_PACKAGE)
    assert result.returncode == 0, result.stdout + result.stderr
    return machine


def test_the_modules_unit_goes_with_the_agent(removed):
    host = removed["host"]

    active = lifecycle.ssh_to(host, f"systemctl is-active {ADDED_INSTANCE}")
    assert active.stdout.strip() != "active", active.stdout
    listed = lifecycle.ssh_to(host, f"ls {UNIT_DIR}")
    assert ADDED_TEMPLATE not in listed.stdout
    assert (
        ADDED_INSTANCE
        not in lifecycle.ssh_to(host, f"ls {UNIT_DIR}/multi-user.target.wants").stdout
    )


def test_a_unit_named_as_the_hub_names_its_own_stays(removed):
    listed = lifecycle.ssh_to(removed["host"], f"ls {UNIT_DIR}")

    assert FOREIGN_UNIT in listed.stdout


def test_the_share_is_still_served_after_the_removal(removed):
    host = removed["host"]

    assert share_count(host) == 1
    served = lifecycle.ssh_to(host, f"systemctl is-active {SMB_UNITS}")
    assert "active" in served.stdout.split(), served.stdout


def test_an_install_after_the_removal_reports_the_share_once(panel, removed):
    install_agent(panel, removed["device_id"], removed["host"], removed["key_id"])

    row = module_walk.wait_state(panel, removed["device_id"], "running", ("running",))
    assert row["code"] == "", row
    view = panel.read(f"/agent/module/samba?device_id={removed['device_id']}")
    assert [share["name"] for share in view["shares"]] == [SHARE["name"]], view
    assert share_count(removed["host"]) == 1
