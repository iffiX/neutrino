"""An enrolment ticket on disk: it outlives a panel restart and is spent once.

The Clients page makes a link; the ticket file under the state root holds its
hash, never the ticket, at mode 0600; the panel restarts; the link joins once
over the pinned agent port and is refused ``ticket_spent`` the second time.
The client row it made is removed at the end.

Run as root on a set-up box with at least one exposed address, so a link has
an address to carry.
"""

import base64
import hashlib
import http.client
import json
import os
import ssl
import stat
import subprocess
import time
import urllib.parse
import zlib

import pytest

import machine_state

TICKET_FILE = "/var/lib/neutrino/hub/enrollment_tickets.json"
PANEL_UNIT = "neutrino_hub_web"
PANEL_RETURN_S = 60
JOIN_TIMEOUT_S = 10
PROTOCOL = 3


def link_payload(link: str) -> dict:
    payload_text = link.removeprefix("neutrino://enroll/")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(padded)))


def pinned_join(url: str, fingerprint: str, ticket: str) -> tuple:
    """One join over TLS held to the link's fingerprint.

    Returns:
        The status and the decoded answer.
    """
    parts = urllib.parse.urlsplit(url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(
        parts.hostname, parts.port, context=context, timeout=JOIN_TIMEOUT_S
    )
    connection.connect()
    certificate = connection.sock.getpeercert(binary_form=True)
    assert hashlib.sha256(certificate).hexdigest() == fingerprint
    body = {
        "ticket": ticket,
        "role": "client",
        "protocol": PROTOCOL,
        "machine_id": "integration-ticket-check",
        "name": "integration-ticket-check",
        "software": "neutrino_client/0.5.0",
        "platform": {"os": "linux", "family": "debian", "arch": "amd64"},
    }
    connection.request(
        "POST",
        "/api/channel/join",
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    answer = connection.getresponse()
    text = answer.read().decode()
    connection.close()
    return answer.status, (json.loads(text) if text else None)


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
    assert status == 200, made
    payload = link_payload(made["link"])
    yield payload
    for row in panel.read("/hub/client")["clients"]:
        if row["name"].startswith("integration-ticket"):
            panel.call("POST", "/hub/client/remove", {"client_id": row["id"]})


def test_a_client_link_survives_a_restart_and_joins_once(panel, client_link, request):
    ticket = client_link["token"]
    digest = hashlib.sha256(ticket.encode()).hexdigest()

    mode = stat.S_IMODE(os.stat(TICKET_FILE).st_mode)
    text = open(TICKET_FILE, encoding="utf-8").read()
    assert mode == 0o600
    assert ticket not in text
    assert [entry["kind"] for entry in json.loads(text)].count("client") == 1
    assert any(entry["token_sha256"] == digest for entry in json.loads(text))

    restart_panel(panel)
    panel.sign_in(request.config.getoption("--password"))

    url = client_link["urls"][0]
    first = pinned_join(url, client_link["fp"], ticket)
    second = pinned_join(url, client_link["fp"], ticket)

    assert first[0] == 200, first
    assert second[0] == 401, second
    assert second[1]["detail"]["code"] == "ticket_spent"
    entries = json.loads(open(TICKET_FILE, encoding="utf-8").read())
    assert all(entry["token_sha256"] != digest for entry in entries)
