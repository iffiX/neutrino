"""The material a ``service`` stream closes with, and where a ``connect``
stream goes, judged for one client now.

A desktop's material is the seat password; the gateway's is the client's
key and a model. A client that is switched off, an entry that is not
published, a share that stopped, and a locked vault each close with their
code and no material. A ``connect`` is judged by the same checks with the
stream limit after the client's own two, and goes to the agent of the
machine that provides the entry, to a declared record's own address, or
to the gateway or the panel on loopback.
"""

import pytest

from neutrino_hub.modules.clients import services
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.channel.constants import CHANNEL_CONNECT_STREAMS_MAX
from neutrino_hub.modules.clients.services import (
    ConnectTarget,
    connect_target,
    entry_port,
    service_material,
)
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from neutrino_hub.modules.services.collector import resolve_entries
from neutrino_hub.modules.services.host_scope import (
    HostScope,
    device_host_for,
    link_scope,
)

ENTRY = {
    "id": "web_gitea",
    "type": "web",
    "title": "Gitea",
    "payload": {"url": "http://192.168.100.1:3000"},
    "is_healthy": True,
    "source": "module",
    "description": "",
    "description_code": "",
    "description_params": {},
    "record_id": None,
    "detail_code": None,
}
RDP_ENTRY = {
    **ENTRY,
    "id": "rdp_s1",
    "type": "rdp",
    "payload": {"host": "192.168.100.7", "port": 21118},
    "device_id": "dev",
}
AI_ENTRY = {**ENTRY, "id": "ai", "type": "ai", "payload": {"endpoint": "http://x"}}
VSCODE_ENTRY = {
    **ENTRY,
    "id": "vscode_dev_alice",
    "title": "VS Code (alice)",
    "payload": {"url": "http://192.168.100.7:8000/", "is_token_required": True},
    "description_code": "vscode_module",
    "description_params": {"host": "192.168.100.7", "account": "alice"},
    "device_id": "dev",
}
LAN = HostScope(
    id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address="192.168.100.1"
)
OVERLAY = HostScope(id="overlay", cidr="100.64.0.0/16", hub_address="100.64.0.1")


class StubPublishedServices:
    """The published list, resolved per scope the way the cache resolves it."""

    def __init__(self, entries, runtime, hub_addresses=()):
        self.listed = list(entries)
        self.runtime = runtime
        self.hub_addresses = set(hub_addresses)

    def entries(self):
        return list(self.listed), "fingerprint"

    def entries_for(self, scope):
        device_hosts = {
            device_id: device_host_for(
                scope,
                self.runtime.device_interfaces.get(device_id, []),
                self.runtime.device_address.get(device_id, ""),
            )
            for device_id in self.runtime.device_address
        }
        return resolve_entries(
            self.listed,
            device_hosts=device_hosts,
            hub_addresses=self.hub_addresses,
            hub_host=scope.hub_address,
        )


class StubDesiredStates:
    def __init__(self):
        self.tokens = {("dev", "alice"): "tkn-alice"}

    def seat_password(self, key):
        return "seat-pass" if key == "dev" else ""  # scan: allow

    def vscode_token(self, key, account):
        return self.tokens.get((key, account), "")


class FakeRuntime:
    def __init__(self, entries=(ENTRY, RDP_ENTRY, AI_ENTRY, VSCODE_ENTRY)):
        self.client_scope = {}
        self.device_interfaces = {}
        self.device_address = {}
        self.published_services = StubPublishedServices(entries, self)
        self.device_shares = DeviceShareRegistry()
        self.desired_states = StubDesiredStates()
        self.served_models = None


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def credential(monkeypatch):
    """The gateway credential minted for a client, without a gateway."""
    minted: list = []

    def fake(registry, client, *, served_models):
        minted.append(client.id)
        return {"api_key": "k", "model": "m"}

    monkeypatch.setattr(services, "client_credential", fake)
    return minted


def sharing(runtime) -> None:
    runtime.device_shares.declare(
        device_id="dev",
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    runtime.device_address["dev"] = "192.168.100.7"
    runtime.device_interfaces["dev"] = [
        {"name": "wt0", "mac": "", "addresses": ["100.64.9.2"]},
        {"name": "enp1s0", "mac": "", "addresses": ["192.168.100.7"]},
    ]


def test_a_desktops_material_is_the_seat_password_alone(config_dir):
    runtime = FakeRuntime()
    sharing(runtime)
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN

    code, params = service_material(runtime, client_id, "rdp_s1")

    assert code == ""
    assert params == {"password": "seat-pass"}  # scan: allow


def test_a_desktop_that_stopped_sharing_is_rdp_not_shared(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "rdp_s1") == (
        "rdp_not_shared",
        {"service_id": "rdp_s1"},
    )


def test_the_gateways_material_is_the_clients_key_and_a_model(config_dir, credential):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = LAN

    code, params = service_material(runtime, client_id, "ai")

    assert code == ""
    assert params == {"api_key": "k", "model": "m"}
    assert credential == [client_id]


def test_a_locked_vault_mints_no_key_and_says_so(config_dir, monkeypatch):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    monkeypatch.setattr(services, "client_credential", lambda *a, **k: None)

    assert service_material(runtime, client_id, "ai") == ("vault_locked", {})


def test_an_entry_that_is_not_published_is_service_unknown(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "rdp_s9") == (
        "service_unknown",
        {"service_id": "rdp_s9"},
    )


def test_a_type_with_no_material_closes_empty(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "web_gitea") == ("", {})


def test_a_disabled_or_forgotten_client_is_handed_nothing(config_dir, credential):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")
    ClientRegistry().set_disabled(client_id, True)

    assert service_material(runtime, client_id, "ai") == ("client_disabled", {})
    assert service_material(runtime, "nobody", "ai") == ("binding_unknown", {})
    assert credential == []


def test_an_entry_outside_the_clients_kinds_is_permission_denied(config_dir):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, ["ai"])

    assert service_material(runtime, client_id, "web_gitea") == (
        "permission_denied",
        {"kind": "web"},
    )


def test_an_entry_of_a_device_outside_the_filter_is_permission_denied(config_dir):
    hosted = {**RDP_ENTRY, "device_id": "d1"}
    runtime = FakeRuntime(entries=(hosted,))
    registry = ClientRegistry()
    client_id = registry.create("alice")

    registry.set_permission(client_id, ["rdp"], {"rdp": ["d2"]})

    assert service_material(runtime, client_id, "rdp_s1") == (
        "permission_denied",
        {"kind": "rdp"},
    )

    registry.set_permission(client_id, ["rdp"], {"rdp": ["d1"]})

    assert service_material(runtime, client_id, "rdp_s1") == (
        "rdp_not_shared",
        {"service_id": "rdp_s1"},
    )


def test_an_unpublished_entry_is_service_unknown_whatever_the_kinds(config_dir):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_default_permission([])

    assert service_material(runtime, client_id, "rdp_s9") == (
        "service_unknown",
        {"service_id": "rdp_s9"},
    )


def test_a_vscode_instances_material_is_its_own_token(config_dir):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "vscode_dev_alice") == (
        "",
        {"token": "tkn-alice"},
    )


def test_a_vscode_token_that_does_not_open_is_vault_locked(config_dir):
    runtime = FakeRuntime()
    runtime.desired_states.tokens = {}
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "vscode_dev_alice") == (
        "vault_locked",
        {},
    )


CLOUDCLI_ENTRY = {
    **ENTRY,
    "id": "cloudcli_dev_alice",
    "title": "CloudCLI (alice)",
    "payload": {
        "url": "http://192.168.100.7:3001/",
        "is_token_required": True,
    },
    "description_code": "cloudcli_module",
    "description_params": {"host": "192.168.100.7", "account": "alice"},
    "device_id": "dev",
}


class MintingDesiredStates(StubDesiredStates):
    def __init__(self):
        super().__init__()
        self.minted: list = []

    def cloudcli_token(self, key, account):
        self.minted.append((key, account))
        return f"fresh-{len(self.minted)}" if key == "dev" else ""


def test_a_cloudcli_instances_material_is_a_token_minted_for_each_answer(config_dir):
    runtime = FakeRuntime(entries=(CLOUDCLI_ENTRY,))
    runtime.desired_states = MintingDesiredStates()
    client_id = ClientRegistry().create("alice")

    first = service_material(runtime, client_id, "cloudcli_dev_alice")
    second = service_material(runtime, client_id, "cloudcli_dev_alice")

    assert (first, second) == (("", {"token": "fresh-1"}), ("", {"token": "fresh-2"}))
    assert runtime.desired_states.minted == [("dev", "alice"), ("dev", "alice")]


def test_a_cloudcli_secret_that_does_not_open_is_vault_locked(config_dir):
    entry = {**CLOUDCLI_ENTRY, "device_id": "elsewhere"}
    runtime = FakeRuntime(entries=(entry,))
    runtime.desired_states = MintingDesiredStates()
    client_id = ClientRegistry().create("alice")

    assert service_material(runtime, client_id, "cloudcli_dev_alice") == (
        "vault_locked",
        {},
    )


# --- where a connect stream goes ---

DECLARED_ENTRY = {
    **ENTRY,
    "id": "declared_nas",
    "type": "web",
    "title": "NAS",
    "payload": {"url": "http://192.168.100.1:5000/"},
    "source": "declared",
    "record_id": "declared_nas",
    "device_id": "",
}
FILE_ENTRY = {
    **ENTRY,
    "id": "samba_dev_media",
    "type": "file",
    "payload": {"protocol": "smb", "host": "192.168.100.7", "share": "media"},
    "device_id": "dev",
}
PANEL_PORT = 8080


def target(runtime, client_id, args, open_count=0) -> tuple:
    return connect_target(
        runtime, client_id, args, open_count=open_count, panel_port=PANEL_PORT
    )


@pytest.fixture
def gateway_port(monkeypatch):
    """The gateway's configured port, without a gateway configuration."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        services, "load_config", lambda: SimpleNamespace(listen_port=8317)
    )


def test_a_connect_is_refused_in_the_service_streams_order_with_the_limit(
    config_dir,
):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert target(runtime, "nobody", {"id": "nothing"}) == (
        "binding_unknown",
        {},
        None,
    )
    registry.set_disabled(client_id, True)
    assert target(
        runtime, client_id, {"id": "nothing"}, CHANNEL_CONNECT_STREAMS_MAX
    ) == ("client_disabled", {}, None)
    registry.set_disabled(client_id, False)
    assert target(
        runtime, client_id, {"id": "nothing"}, CHANNEL_CONNECT_STREAMS_MAX
    ) == ("connect_limit", {"limit": CHANNEL_CONNECT_STREAMS_MAX}, None)
    assert target(
        runtime, client_id, {"id": "nothing"}, CHANNEL_CONNECT_STREAMS_MAX - 1
    ) == ("service_unknown", {"service_id": "nothing"}, None)
    registry.set_permission(client_id, ["ai"])
    assert target(runtime, client_id, {"id": "rdp_s1"}) == (
        "permission_denied",
        {"kind": "rdp"},
        None,
    )
    registry.set_permission(client_id, ["rdp"])
    assert target(runtime, client_id, {"id": "rdp_s1"}) == (
        "rdp_not_shared",
        {"service_id": "rdp_s1"},
        None,
    )


def test_a_device_filter_refuses_a_connect_to_another_devices_entry(config_dir):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.set_permission(client_id, ["web"], {"web": ["other"]})

    assert target(runtime, client_id, {"id": "vscode_dev_alice"}) == (
        "permission_denied",
        {"kind": "web"},
        None,
    )


def test_the_panel_is_its_own_kind_on_loopback_at_the_panels_http_port(config_dir):
    runtime = FakeRuntime()
    registry = ClientRegistry()
    client_id = registry.create("alice")

    assert target(runtime, client_id, {"is_panel": True}) == (
        "",
        {},
        ConnectTarget("", "127.0.0.1", PANEL_PORT),
    )

    registry.set_permission(client_id, ["web", "terminal"])

    assert target(runtime, client_id, {"is_panel": True}) == (
        "permission_denied",
        {"kind": "panel"},
        None,
    )


def test_an_entry_a_machine_provides_goes_to_its_agent_at_the_entrys_port(
    config_dir,
):
    runtime = FakeRuntime(entries=(VSCODE_ENTRY, RDP_ENTRY, FILE_ENTRY))
    sharing(runtime)
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = OVERLAY

    assert [
        target(runtime, client_id, {"id": entry_id})[2]
        for entry_id in ("vscode_dev_alice", "rdp_s1", "samba_dev_media")
    ] == [
        ConnectTarget("dev", "", 8000),
        ConnectTarget("dev", "", 21118),
        ConnectTarget("dev", "", 445),
    ]


def test_a_declared_record_is_dialled_at_its_own_address_whatever_the_scope(
    config_dir,
):
    runtime = FakeRuntime(entries=(DECLARED_ENTRY,))
    runtime.published_services.hub_addresses = {"192.168.100.1"}
    client_id = ClientRegistry().create("alice")
    runtime.client_scope[client_id] = OVERLAY

    assert target(runtime, client_id, {"id": "declared_nas"}) == (
        "",
        {},
        ConnectTarget("", "192.168.100.1", 5000),
    )


def test_the_gateway_is_dialled_on_loopback_at_its_port(config_dir, gateway_port):
    runtime = FakeRuntime()
    client_id = ClientRegistry().create("alice")

    assert target(runtime, client_id, {"id": "ai"}) == (
        "",
        {},
        ConnectTarget("", "127.0.0.1", 8317),
    )


@pytest.mark.parametrize(
    "entry, port",
    [
        ({"type": "web", "payload": {"url": "http://h:3000/"}}, 3000),
        ({"type": "web", "payload": {"url": "http://h/"}}, 80),
        ({"type": "web", "payload": {"url": "https://h/x"}}, 443),
        ({"type": "port", "payload": {"host": "h", "port": 2222}}, 2222),
        ({"type": "rdp", "payload": {"host": "h", "port": 21118}}, 21118),
        ({"type": "file", "payload": {"host": "h", "share": "s"}}, 445),
        ({"type": "ai", "payload": {"endpoint": "http://h:8317"}}, 0),
    ],
)
def test_an_entrys_port_follows_its_type(entry, port):
    assert entry_port(entry) == port
