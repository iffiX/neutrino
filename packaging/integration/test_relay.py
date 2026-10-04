"""The relay end to end: a client joins through the server's public address.

The box stores an SSH key, points the relay at a server the tester owns and
turns it on; the relay reads ``connected``, a client link names the relay's
address last, and a client that is handed only that address joins, says
hello and is told it came through the relay. Everything the test made is
removed at the end, and the relay is off again.

The server is set up as docs/guide/hub/relay.md says; the lab's VPS VM from
``packaging/lab/make_vps.sh`` is one. Run on a set-up box:

    NEUTRINO_PANEL_PASSWORD=... NEUTRINO_RELAY_HOST=192.168.124.132 \\
    NEUTRINO_RELAY_KEY_FILE=/root/relay_key python3 -m pytest test_relay.py -q

``NEUTRINO_RELAY_ACCOUNT`` (default ``relay``), ``NEUTRINO_RELAY_SSH_PORT``
(default 22) and ``NEUTRINO_RELAY_PUBLIC_PORT`` (default 18443) say the rest.
The key file is read and sent to the panel; it is never printed.
"""

import os
import time

import pytest

RELAY_HOST_ENV = "NEUTRINO_RELAY_HOST"
RELAY_KEY_FILE_ENV = "NEUTRINO_RELAY_KEY_FILE"

if not os.environ.get(RELAY_HOST_ENV) or not os.environ.get(RELAY_KEY_FILE_ENV):
    pytest.skip(
        f"no relay server for this run: set {RELAY_HOST_ENV} and {RELAY_KEY_FILE_ENV}",
        allow_module_level=True,
    )
connect_probe = pytest.importorskip(
    "connect_probe",
    reason="no neutrino_agent package in the checkout or the installed agent",
)
Channel = connect_probe.Channel
join = connect_probe.join
parse_client_link = connect_probe.parse_client_link
take_state = connect_probe.take_state
BindingHttpClient = connect_probe.BindingHttpClient

RELAY_ACCOUNT_ENV = "NEUTRINO_RELAY_ACCOUNT"
RELAY_SSH_PORT_ENV = "NEUTRINO_RELAY_SSH_PORT"
RELAY_PUBLIC_PORT_ENV = "NEUTRINO_RELAY_PUBLIC_PORT"
CONNECTED_WITHIN_S = 90
CLIENT_NAME = "integration-relay"


@pytest.fixture
def relay(panel):
    """The relay on and pointed at the tester's server; off and keyless after."""
    host = os.environ[RELAY_HOST_ENV]
    key_file = os.environ[RELAY_KEY_FILE_ENV]
    with open(key_file, encoding="utf-8") as stream:
        private_key = stream.read()
    status, key = panel.call(
        "POST",
        "/hub/credential/ssh_key/add",
        {"name": CLIENT_NAME, "private_key": private_key},
    )
    assert status == 200, key
    settings = {
        "host": host,
        "ssh_port": int(os.environ.get(RELAY_SSH_PORT_ENV, "22")),
        "account": os.environ.get(RELAY_ACCOUNT_ENV, "relay"),
        "key_id": key["id"],
        "public_port": int(os.environ.get(RELAY_PUBLIC_PORT_ENV, "18443")),
    }
    try:
        status, view = panel.call("POST", "/hub/overlay/relay/set", settings)
        assert status == 200, view
        status, view = panel.call(
            "POST", "/hub/overlay/set", {"relay": {"is_enabled": True}}
        )
        assert status == 200, view
        yield settings
    finally:
        panel.call("POST", "/hub/overlay/set", {"relay": {"is_enabled": False}})
        panel.call("POST", "/hub/credential/ssh_key/remove", {"key_id": key["id"]})
        for row in panel.read("/hub/client")["clients"]:
            if row["name"].startswith(CLIENT_NAME):
                panel.call("POST", "/hub/client/remove", {"client_id": row["id"]})


def connected_view(panel) -> dict:
    """The relay's view once it reads ``connected``."""
    deadline = time.monotonic() + CONNECTED_WITHIN_S
    view = panel.read("/hub/overlay/relay")
    while view["state"] != "connected" and time.monotonic() < deadline:
        time.sleep(2)
        view = panel.read("/hub/overlay/relay")
    return view


def test_a_client_handed_only_the_relay_address_joins_through_it(panel, relay):
    relay_url = f"https://{relay['host']}:{relay['public_port']}"

    view = connected_view(panel)
    assert view["state"] == "connected", view
    assert view["url"] == relay_url
    assert view["host_key_fingerprint"].startswith("SHA256:")

    status, made = panel.call(
        "POST", "/hub/client/enrollment/create", {"name": CLIENT_NAME}
    )
    assert status == 200, made
    urls, ticket, fingerprint = parse_client_link(made["link"])
    assert urls[-1] == relay_url

    gateway_url, binding_id, token = join([relay_url], ticket, fingerprint)
    channel = Channel(gateway_url, fingerprint)
    try:
        welcome = channel.open(binding_id, token)
        state = take_state(channel)
        kinds = {row["key"]: row for row in panel.read("/hub/overlay")["kinds"]}
    finally:
        channel.close()
        BindingHttpClient(gateway_url=gateway_url, fingerprint=fingerprint).leave(
            binding_id, token
        )

    assert welcome["role"] == "hub"
    assert state["reached_through"] == "relay"
    assert state["urls"][-1] == relay_url
    assert kinds["relay"]["is_active"] is True
    assert kinds["relay"]["client_count"] >= 1
