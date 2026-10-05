"""The files adapter on Windows, the resident's half.

The address plan: the adapter at the network's first address, one address
per machine from the second up, kept per hub and machine across a restart.
The SOCKS endpoint, driven by a real SOCKS5 client over the loopback: it
takes ``<address>:445`` of a machine it knows behind its login and hands it
to the connector naming a ``file`` entry of that machine, and refuses every
other address, port, command and login. The hold on the daemon: ``up`` with
the endpoint before a mount, every failure the one refusal, ``down`` only
while the daemon serves this resident.
"""

import socket
import struct
import threading

import pytest

from neutrino_client.exceptions import ShareAttachError
from neutrino_client.platforms.base import ClientPlatform
from neutrino_client.services.files_adapter import (
    FilesAdapter,
    FilesAddressPlan,
    FilesSocksEndpoint,
    files_addresses,
    files_machine,
)
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import discard

FIRST = "198.19.255.2"  # scan: allow
SECOND = "198.19.255.3"  # scan: allow
LAST = "198.19.255.253"  # scan: allow
ADAPTER = "198.19.255.1"  # scan: allow
SHARE_ENTRY = {
    "hub_id": "h1",
    "id": "samba:media",
    "type": "file",
    "device_id": "d1",
    "is_healthy": True,
    "payload": {"host": "192.168.10.20", "share": "media"},
}


@pytest.fixture
def store(tmp_path):
    return ClientServiceStore(path=str(tmp_path / "state.json"))


@pytest.fixture
def plan(store):
    return FilesAddressPlan(store=store)


class Far:
    """One end of a socket pair standing in for a connect stream."""

    def __init__(self):
        self.near, self.peer = socket.socketpair()
        self.is_closed = False

    def recv(self, size):
        return self.near.recv(size)

    def sendall(self, data):
        self.near.sendall(data)

    def close(self):
        self.is_closed = True
        try:
            self.near.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.near.close()


class Connector:
    def __init__(self):
        self.calls = []
        self.fars = []
        self.error = None

    def __call__(self, hub_id, entry_id):
        self.calls.append((hub_id, entry_id))
        if self.error is not None:
            raise self.error
        far = Far()
        self.fars.append(far)
        return far


@pytest.fixture
def connector():
    return Connector()


@pytest.fixture
def endpoint(plan, connector):
    served = FilesSocksEndpoint(
        plan=plan,
        connector=connector,
        entries_of=lambda: [dict(SHARE_ENTRY)],
        log=discard,
    )
    served.start()
    yield served
    served.stop()


def socks_client(endpoint, *, methods=(2,), user=None, password=None):
    """A SOCKS5 client past the greeting and the login; None when refused."""
    client = socket.create_connection(("127.0.0.1", endpoint.port), timeout=5)
    client.sendall(bytes((5, len(methods))) + bytes(methods))
    chosen = client.recv(2)
    if chosen != b"\x05\x02":
        client.close()
        return chosen
    name = (endpoint.user if user is None else user).encode()
    secret = (endpoint.password if password is None else password).encode()
    client.sendall(bytes((1, len(name))) + name + bytes((len(secret),)) + secret)
    status = client.recv(2)
    if status != b"\x01\x00":
        client.close()
        return status
    return client


def connect(client, address, port, *, command=1):
    client.sendall(
        bytes((5, command, 0, 1)) + socket.inet_aton(address) + struct.pack(">H", port)
    )
    return client.recv(10)


def test_the_adapter_takes_the_first_address_and_machines_the_rest():
    addresses = files_addresses()

    assert addresses[0] == FIRST
    assert addresses[-1] == LAST
    assert ADAPTER not in addresses
    assert len(addresses) == 252
    assert "198.19.255.254" not in addresses  # scan: allow


def test_a_machine_is_its_device_or_a_declared_records_host():
    assert files_machine(SHARE_ENTRY) == "d1"
    assert files_machine({"payload": {"host": "nas.lan"}}) == "nas.lan"
    assert files_machine({"device_id": "", "payload": {"host": "nas.lan"}}) == (
        "nas.lan"
    )


def test_a_managed_machines_share_is_keyed_by_its_name_whatever_way_in():
    """The hub sends no device id on the channel, and the host of a share on
    the hub's own machine is the address the client reached the hub at."""
    over_lan = {
        "source": "module",
        "device_name": "nmxhub",
        "payload": {"host": "192.168.122.82", "share": "t1share"},
    }
    over_relay = dict(over_lan, payload={"host": "192.168.10.164"})

    assert files_machine(over_lan) == files_machine(over_relay) == "nmxhub"
    declared = {
        "source": "declared",
        "device_name": "nmxhub",
        "payload": {"host": "nas"},
    }
    assert files_machine(declared) == "nas"
    assert files_machine({"source": "module", "payload": {"host": "nas"}}) == "nas"


def test_each_machine_keeps_its_address_per_hub_across_a_restart(store, plan):
    assert plan.address_for("h1", "d1") == FIRST
    assert plan.address_for("h1", "d2") == SECOND
    assert plan.address_for("h1", "d1") == FIRST
    assert plan.address_for("h2", "d1") == "198.19.255.4"  # scan: allow

    again = FilesAddressPlan(store=ClientServiceStore(path=store._path))
    assert again.address_for("h1", "d2") == SECOND
    assert again.target_of(FIRST) == ("h1", "d1")
    assert again.target_of(LAST) is None


def test_a_full_table_gives_away_only_an_address_no_mount_names(store):
    for index, address in enumerate(files_addresses()):
        store.set_files_address(address, "h1", f"d{index}")
    plan = FilesAddressPlan(store=store, held_of=lambda: {FIRST})

    assert plan.address_for("h2", "new") == SECOND
    assert plan.target_of(FIRST) == ("h1", "d0")
    assert plan.target_of(SECOND) == ("h2", "new")


def test_a_table_every_mount_names_is_refused(store):
    for index, address in enumerate(files_addresses()):
        store.set_files_address(address, "h1", f"d{index}")
    plan = FilesAddressPlan(store=store, held_of=lambda: set(files_addresses()))

    with pytest.raises(ShareAttachError) as raised:
        plan.address_for("h2", "new")

    assert raised.value.code == "files_adapter_unavailable"
    assert raised.value.detail == "addresses_exhausted"


def test_leaving_a_hub_drops_its_addresses_no_mount_names(store):
    plan = FilesAddressPlan(store=store, held_of=lambda: {SECOND})
    plan.address_for("h1", "d1")
    plan.address_for("h1", "d2")
    plan.address_for("h2", "d3")

    plan.forget_hub("h1")

    assert store.files_addresses() == {
        SECOND: {"hub_id": "h1", "machine": "d2"},
        "198.19.255.4": {"hub_id": "h2", "machine": "d3"},  # scan: allow
    }


def test_a_known_machine_on_445_reaches_its_file_entry(plan, endpoint, connector):
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)

    reply = connect(client, FIRST, 445)

    assert reply[:2] == b"\x05\x00"
    assert connector.calls == [("h1", "samba:media")]
    far = connector.fars[0]
    client.sendall(b"negotiate")
    assert far.peer.recv(64) == b"negotiate"
    far.peer.sendall(b"response")
    assert client.recv(64) == b"response"
    client.close()
    assert far.peer.recv(64) == b""


def test_the_far_end_ending_closes_the_client(plan, endpoint, connector):
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)
    connect(client, FIRST, 445)

    connector.fars[0].peer.sendall(b"last words")
    connector.fars[0].peer.close()

    received = b""
    while True:
        chunk = client.recv(64)
        if not chunk:
            break
        received += chunk
    assert received == b"last words"


@pytest.mark.parametrize(
    "address, port",
    [(FIRST, 139), (FIRST, 80), (SECOND, 445), ("192.168.10.20", 445)],
)
def test_any_other_address_or_port_is_not_allowed(
    plan, endpoint, connector, address, port
):
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)

    reply = connect(client, address, port)

    assert reply[:2] == b"\x05\x02"
    assert connector.calls == []


def test_a_name_or_an_ipv6_target_is_not_spoken(plan, endpoint, connector):
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)
    client.sendall(b"\x05\x01\x00\x03\x07nas.lan\x01\xbd")

    assert client.recv(10)[:2] == b"\x05\x08"
    assert connector.calls == []


def test_a_command_other_than_connect_is_not_spoken(plan, endpoint, connector):
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)

    reply = connect(client, FIRST, 445, command=3)

    assert reply[:2] == b"\x05\x07"
    assert connector.calls == []


def test_a_client_offering_no_login_is_refused(endpoint, connector):
    assert socks_client(endpoint, methods=(0,)) == b"\x05\xff"


@pytest.mark.parametrize("field", ["user", "password"])
def test_a_wrong_login_is_refused(endpoint, connector, field):
    assert socks_client(endpoint, **{field: "guess"}) == b"\x01\x01"


def test_a_machine_with_no_share_published_is_unreachable(plan, endpoint, connector):
    plan.address_for("h1", "gone")
    client = socks_client(endpoint)

    reply = connect(client, FIRST, 445)

    assert reply[:2] == b"\x05\x04"
    assert connector.calls == []


def test_a_hub_that_refuses_the_stream_is_a_refusal(plan, endpoint, connector):
    plan.address_for("h1", "d1")
    connector.error = ConnectionError("permission_denied")
    client = socks_client(endpoint)

    reply = connect(client, FIRST, 445)

    assert reply[:2] == b"\x05\x05"


def test_each_start_makes_a_fresh_login_and_a_stop_ends_every_relay(plan, connector):
    endpoint = FilesSocksEndpoint(
        plan=plan, connector=connector, entries_of=lambda: [SHARE_ENTRY], log=discard
    )
    endpoint.start()
    first = (endpoint.port, endpoint.user, endpoint.password)
    plan.address_for("h1", "d1")
    client = socks_client(endpoint)
    connect(client, FIRST, 445)

    endpoint.stop()

    assert client.recv(64) == b""
    assert endpoint.port == 0 and not endpoint.is_running
    endpoint.start()
    try:
        assert endpoint.user != first[1] and endpoint.password != first[2]
        assert len(endpoint.password) >= 32
    finally:
        endpoint.stop()


class FilesPlatform(ClientPlatform):
    def files_daemon_address(self):
        return "\\\\.\\pipe\\neutrino_client_files"


class Daemon:
    """The daemon behind the pipe, scripted."""

    def __init__(self):
        self.requests = []
        self.answers = {}
        self.error = None
        self.serving = 0

    def __call__(self, address, request):
        assert address == "\\\\.\\pipe\\neutrino_client_files"
        self.requests.append(dict(request))
        if self.error is not None:
            raise self.error
        verb = request["verb"]
        if verb in self.answers:
            return self.answers[verb]
        if verb == "up":
            self.serving = request["port"]
        if verb == "down":
            self.serving = 0
        return {"is_up": bool(self.serving), "port": self.serving}


@pytest.fixture
def daemon():
    return Daemon()


@pytest.fixture
def adapter(plan, connector, daemon):
    endpoint = FilesSocksEndpoint(plan=plan, connector=connector, log=discard)
    held = FilesAdapter(
        platform=FilesPlatform(),
        plan=plan,
        endpoint=endpoint,
        ask=daemon,
        log=discard,
    )
    yield held, endpoint
    endpoint.stop()


def test_a_mount_brings_the_adapter_up_for_this_endpoint(adapter, daemon):
    held, endpoint = adapter

    assert held.host("h1", "d1") == FIRST

    assert daemon.requests == [
        {
            "verb": "up",
            "port": endpoint.port,
            "user": endpoint.user,
            "password": endpoint.password,
        }
    ]
    assert endpoint.is_running


def test_every_mount_asks_again_so_a_restarted_service_comes_back(adapter, daemon):
    held, _ = adapter

    held.host("h1", "d1")
    held.host("h1", "d2")

    assert [request["verb"] for request in daemon.requests] == ["up", "up"]


def test_a_missing_or_stopped_service_is_the_one_refusal(adapter, daemon):
    held, _ = adapter
    daemon.error = FileNotFoundError(2, "The system cannot find the file specified")

    with pytest.raises(ShareAttachError) as raised:
        held.host("h1", "d1")

    assert raised.value.code == "files_adapter_unavailable"
    assert raised.value.detail == "NeutrinoClientFiles does not answer"


def test_a_refusing_service_names_what_failed(adapter, daemon):
    held, _ = adapter
    daemon.answers["up"] = {
        "code": "files_adapter_unavailable",
        "params": {"detail": "the adapter neutrino_files is not up"},
    }

    with pytest.raises(ShareAttachError) as raised:
        held.host("h1", "d1")

    assert raised.value.detail == "the adapter neutrino_files is not up"


def test_an_answer_that_is_not_up_is_refused(adapter, daemon):
    held, _ = adapter
    daemon.answers["up"] = {"is_up": False, "port": 1}

    with pytest.raises(ShareAttachError) as raised:
        held.host("h1", "d1")

    assert raised.value.detail == "not_up"


def test_a_platform_with_no_adapter_is_refused(plan, connector):
    endpoint = FilesSocksEndpoint(plan=plan, connector=connector, log=discard)
    held = FilesAdapter(
        platform=ClientPlatform(), plan=plan, endpoint=endpoint, log=discard
    )
    try:
        with pytest.raises(ShareAttachError) as raised:
            held.host("h1", "d1")
    finally:
        endpoint.stop()

    assert raised.value.detail == "unsupported_platform"


def test_down_takes_the_adapter_down_while_it_serves_this_resident(adapter, daemon):
    held, _ = adapter
    held.host("h1", "d1")

    held.down()

    assert [request["verb"] for request in daemon.requests] == [
        "up",
        "status",
        "down",
    ]


def test_down_leaves_an_adapter_another_resident_asked_for_last(adapter, daemon):
    held, _ = adapter
    held.host("h1", "d1")
    daemon.serving = 1

    held.down()

    assert [request["verb"] for request in daemon.requests] == ["up", "status"]


def test_down_asks_nothing_when_nothing_was_brought_up(adapter, daemon):
    held, _ = adapter

    held.down()

    assert daemon.requests == []


def test_a_down_nobody_hears_is_not_an_error(adapter, daemon):
    held, _ = adapter
    held.host("h1", "d1")
    daemon.error = OSError("gone")

    held.down()


def test_a_quit_takes_the_adapter_down_and_stops_the_endpoint(adapter, daemon):
    held, endpoint = adapter
    held.host("h1", "d1")

    held.stop()

    assert daemon.requests[-1] == {"verb": "down"}
    assert not endpoint.is_running


def test_two_threads_mounting_at_once_both_get_their_address(adapter, daemon):
    held, _ = adapter
    found = {}

    def mount(machine):
        found[machine] = held.host("h1", machine)

    threads = [threading.Thread(target=mount, args=(f"d{n}",)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(found.values())) == 8


def test_the_daemons_probe_is_refused_without_a_log_line(plan, connector):
    lines = []
    endpoint = FilesSocksEndpoint(plan=plan, connector=connector, log=lines.append)
    endpoint.start()
    try:
        client = socks_client(endpoint)
        reply = connect(client, "198.19.255.254", 9)  # scan: allow
        other = socks_client(endpoint)
        connect(other, "198.19.255.9", 445)  # scan: allow
    finally:
        endpoint.stop()

    assert reply[:2] == b"\x05\x02"
    assert not any("198.19.255.254" in line for line in lines)  # scan: allow
    assert "files endpoint refused 198.19.255.9:445" in lines  # scan: allow


def test_an_adapter_held_by_another_account_is_its_own_refusal(adapter, daemon):
    held, _ = adapter
    daemon.answers["up"] = {"code": "files_adapter_in_use", "params": {}}

    with pytest.raises(ShareAttachError) as raised:
        held.host("h1", "d1")

    assert raised.value.code == "files_adapter_in_use"
    assert raised.value.detail == ""
