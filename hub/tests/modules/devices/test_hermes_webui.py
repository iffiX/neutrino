"""Hermes WebUI on the hub: its file, the configuration the state sends, its two containers.

What these pin: the first install generates the token secret and the
webui's password once and keeps them; the state carries ``{secret,
password}`` opened, the login cookie's name, ``hermes_session_`` and the
device id's first 12 characters, and the app's local name;
the two hub containers as the module's page lists them, the cookie's name in
the webui's environment, with the gateway's address on a
managed machine and on the hub's own; no container while the password does
not open; and the manifest's four entries naming the tested pair by digest.
"""

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.devices import hermes_webui
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.hub_containers import compose_hub_containers
from neutrino_hub.modules.devices.manifests import load_module_manifests
from tests.conftest import unlock_vault

DEVICE = "dev-1"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
WEBUI_DIGEST = "sha256:e507cafa7b112de9abd58348423ded28a8182539e6ebb5f95be603f20aff52e6"
AGENT_DIGEST = "sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7"
WEBUI_SOURCES = [
    "ghcr.io/nesquena/hermes-webui",
    "ghcr.nju.edu.cn/nesquena/hermes-webui",
    "ghcr.m.daocloud.io/nesquena/hermes-webui",
]


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    return tmp_path


@pytest.fixture
def store(config_dir, monkeypatch):
    unlock_vault(monkeypatch, config_dir)
    return DesiredStateStore()


def opened(stored: dict, key: str, aad: bytes) -> str:
    return unseal_bytes(stored[key], aad).decode()


def test_the_first_install_generates_both_secrets_once_and_keeps_them(store):
    first = hermes_webui.ensure_config(store, DEVICE)
    again = hermes_webui.ensure_config(store, DEVICE)

    assert first == again == store.read(DEVICE, "hermes_webui")
    assert set(first) == {"secret_sealed", "password_sealed"}
    secret = opened(first, "secret_sealed", b"device_hermes_webui:secret")
    password = opened(first, "password_sealed", b"device_hermes_webui:password")
    assert len(secret) >= 40 and len(password) >= 40 and secret != password


def test_the_state_carries_both_secrets_opened_and_the_local_name(store):
    stored = hermes_webui.ensure_config(store, DEVICE)

    config = store.agent_config(
        DEVICE, "hermes_webui", stored, LINUX, machine_slug="argon"
    )

    assert config == {
        "secret": opened(stored, "secret_sealed", b"device_hermes_webui:secret"),
        "password": opened(stored, "password_sealed", b"device_hermes_webui:password"),
        "cookie_name": "hermes_session_dev-1",
        "local_name": "hermes-webui.argon.localhost",
    }


def test_a_file_with_nothing_sealed_sends_empty_secrets():
    assert hermes_webui.agent_config({}, DEVICE) == {
        "secret": "",
        "password": "",
        "cookie_name": "hermes_session_dev-1",
        "local_name": "",
    }


def test_the_cookie_is_named_for_the_first_12_characters_of_the_device_id():
    first = hermes_webui.cookie_name("a9cae941666241e39f3b2213ad5290bb")
    second = hermes_webui.cookie_name("0d1e2f3041526374a9cae941666241e3")

    assert first == "hermes_session_a9cae9416662"
    assert second == "hermes_session_0d1e2f304152"


def test_the_two_containers_are_composed_as_the_module_s_page_lists_them(store):
    stored = hermes_webui.ensure_config(store, DEVICE)
    key = ai_keys.ensure_module_key(store, DEVICE, "hermes_webui", "argon")
    store.set_want(DEVICE, "hermes_webui", "running")
    password = opened(stored, "password_sealed", b"device_hermes_webui:password")
    gateway = [
        "NEUTRINO_GATEWAY_URL=http://host.containers.internal:8317",
        f"NEUTRINO_GATEWAY_KEY={key}",
    ]

    composed = compose_hub_containers(store, DEVICE, LINUX)

    assert composed == [
        {
            "module": "hermes_webui",
            "name": "neutrino_hermes_webui_agent",
            "image": {
                "digest": AGENT_DIGEST,
                "sources": ["docker.io/nousresearch/hermes-agent"],
            },
            "ports": [],
            "volumes": [
                "neutrino_hermes_webui_home:/opt/data",
                "neutrino_hermes_webui_agent:/opt/hermes",
            ],
            "environment": ["HERMES_UID=1024", "HERMES_GID=1024", *gateway],
            "command": "gateway run",
            "is_autostart": True,
            "services": [],
            "source_sets": ["pypi"],
            "after": [],
            "page_port": 0,
        },
        {
            "module": "hermes_webui",
            "name": "neutrino_hermes_webui",
            "image": {"digest": WEBUI_DIGEST, "sources": WEBUI_SOURCES},
            "ports": [],
            "volumes": [
                "neutrino_hermes_webui_home:/home/hermeswebui/.hermes",
                "neutrino_hermes_webui_workspace:/workspace",
                "neutrino_hermes_webui_agent:/home/hermeswebui/.hermes/hermes-agent:ro",
                "neutrino_hermes_webui_app:/app",
            ],
            "environment": [
                "WANTED_UID=1024",
                "WANTED_GID=1024",
                "HERMES_WEBUI_STATE_DIR=/home/hermeswebui/.hermes/webui",
                f"HERMES_WEBUI_PASSWORD={password}",
                "HERMES_WEBUI_COOKIE_NAME=hermes_session_dev-1",
                *gateway,
            ],
            "command": "",
            "is_autostart": True,
            "services": [],
            "source_sets": ["pypi"],
            "after": ["neutrino_hermes_webui_agent"],
            "page_port": 8787,
        },
    ]


def test_on_the_hub_s_own_machine_the_containers_reach_the_gateway_s_own_port(
    store, config_dir
):
    (config_dir / "cliproxyapi").mkdir()
    (config_dir / "cliproxyapi" / "cliproxyapi.json").write_text(
        '{"listen_port": 8400}'
    )
    hermes_webui.ensure_config(store, DEVICE)
    store.set_want(DEVICE, "hermes_webui", "installed")

    composed = compose_hub_containers(store, DEVICE, LINUX, is_hub_machine=True)

    for container in composed:
        assert (
            "NEUTRINO_GATEWAY_URL=http://host.containers.internal:8400"
            in container["environment"]
        )
        assert container["is_autostart"] is False


def test_no_container_is_composed_while_the_password_does_not_open(store):
    store.set_want(DEVICE, "hermes_webui", "running")

    assert compose_hub_containers(store, DEVICE, LINUX) == []

    store.write(DEVICE, "hermes_webui", {"port": 8787, "password_sealed": {"x": 1}})

    assert compose_hub_containers(store, DEVICE, LINUX) == []


def test_every_entry_names_the_tested_pair_by_digest_and_the_pypi_set():
    manifest = load_module_manifests()["hermes_webui"]

    assert manifest["license"] == "MIT"
    assert set(manifest["platforms"]) == {
        "linux",
        "windows-amd64",
        "darwin-arm64",
        "darwin-amd64",
    }
    for entry in manifest["platforms"].values():
        assert entry["runner"] == "container"
        assert entry["install"]["method"] == "container"
        params = entry["install"]["params"]
        assert "releases" not in params
        assert params["version"] == "0.52.492"
        assert params["source_sets"] == ["pypi"]
        assert params["artifacts"] == [
            {
                "name": "webui",
                "kind": "image",
                "digest": WEBUI_DIGEST,
                "sources": WEBUI_SOURCES,
            },
            {
                "name": "agent",
                "kind": "image",
                "digest": AGENT_DIGEST,
                "sources": ["docker.io/nousresearch/hermes-agent"],
            },
        ]
