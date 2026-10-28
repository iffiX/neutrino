"""An enrolment ticket on disk: it outlives a panel restart and is spent once.

The Clients page makes a link; the ticket file under the state root holds its
hash, never the ticket, at mode 0600; the panel restarts; the link joins once
through a transport of the check's own and is refused ``ticket_spent`` the
second time. The client leaves at the end, and the row it made is removed.

Run as root on a set-up box with at least one exposed address, so a link has
an address to carry.
"""

import hashlib
import json
import os
import stat
import subprocess
import time

import pytest

import machine_state

connect_probe = pytest.importorskip(
    "connect_probe", reason="needs the agent package for the client's transport"
)

TICKET_FILE = "/var/lib/neutrino/hub/enrollment_tickets.json"
PANEL_UNIT = "neutrino_hub_web"
PANEL_RETURN_S = 60


def restart_panel(panel) -> None:
    """Restart the panel's unit and wait until its port answers again."""
    subprocess.run(["systemctl", "restart", PANEL_UNIT], check=True)
    deadline = time.monotonic() + PANEL_RETURN_S
    while time.monotonic() < deadline:
        if machine_state.is_active(PANEL_UNIT) and panel.status("GET", "/hub/network"):
            return
        time.sleep(1.0)
    raise AssertionError("the panel never answered again after the restart")


@pytest.fixture
def client_link(panel):
    """A client link from the Clients page, and its row removed afterwards."""
    if os.geteuid() != 0:
        pytest.skip("reads the state root and restarts the panel: run as root")
    status, made = panel.call(
        "POST", "/hub/client/enrollment/create", {"name": "integration-ticket"}
    )
    if status == 400 and made.get("detail", {}).get("code") == "no_reachable_address":
        pytest.skip("this box exposes no address a client could be sent to")
    assert status == 200, made
    yield connect_probe.parse_client_link(made["link"])
    for row in panel.read("/hub/client")["clients"]:
        if row["name"].startswith("integration-ticket"):
            panel.call("POST", "/hub/client/remove", {"client_id": row["id"]})


def test_a_client_link_survives_a_restart_and_joins_once(panel, client_link, request):
    addresses, ticket, hub_key = client_link
    digest = hashlib.sha256(ticket.encode()).hexdigest()

    mode = stat.S_IMODE(os.stat(TICKET_FILE).st_mode)
    text = open(TICKET_FILE, encoding="utf-8").read()
    assert mode == 0o600
    assert ticket not in text
    assert [entry["kind"] for entry in json.loads(text)].count("client") == 1
    assert any(entry["token_sha256"] == digest for entry in json.loads(text))

    restart_panel(panel)
    panel.sign_in(request.config.getoption("--password"))

    first = connect_probe.Client()
    second = connect_probe.Client()
    first.start()
    second.start()
    try:
        first.join(addresses, ticket, hub_key)
        with pytest.raises(connect_probe.GatewayUnreachable, match="ticket_spent"):
            second.join(addresses, ticket, hub_key)
    finally:
        first.leave()
        first.close()
        second.close()

    assert first.binding_id
    entries = json.loads(open(TICKET_FILE, encoding="utf-8").read())
    assert all(entry["token_sha256"] != digest for entry in entries)
