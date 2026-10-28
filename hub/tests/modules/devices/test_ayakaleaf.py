"""Ayakaleaf on the hub: its file, the configuration the state sends, its three containers.

What these pin: the first install generates the token secret, the
administrator's password and the app's session and invitation secrets once
and keeps them; the state carries ``{secret, password}`` opened, the session
cookie's name, ``ayakaleaf_sid_`` and the device id's first 12 characters,
the app's local name, and never the session or invitation secret; the three hub containers as the module's
page lists them, the app after the other two with its 60-second stop; the
four ``AI_`` variables while the gateway serves a model and none while it
serves none; no container while a secret does not open; and the manifest's
four entries naming the three images, the ``oci`` feed and the ``ctan`` set.
"""

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.devices import ayakaleaf
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.hub_containers import compose_hub_containers
from neutrino_hub.modules.devices.manifests import load_module_manifests
from tests.conftest import unlock_vault

DEVICE = "dev-1"
DEVICE_ID = "a9cae941666241e39f3b2213ad5290bb"  # scan: allow
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
APP_DIGEST = "sha256:5f84c7f2d0230dd558130ca2901f603d4e0bfe021054879efea1b7fece2f4f1c"
MONGO_DIGEST = "sha256:8e7d23aa641b0ec6c86418866d5d18d74d5abf89061bc5db7bc4b80929021ef6"
REDIS_DIGEST = "sha256:bd28fff4b665fdf1b73e8b5b73ec05d2f858f4fa3c8ea0d7c9bc09f7f6bf7039"
APP_SOURCES = [
    "ghcr.io/ayaka-notes/overleaf-pro",
    "ghcr.nju.edu.cn/ayaka-notes/overleaf-pro",
    "ghcr.m.daocloud.io/ayaka-notes/overleaf-pro",
]
FIXED = [
    "OVERLEAF_MONGO_URL=mongodb://neutrino_ayakaleaf_mongo/sharelatex",
    "OVERLEAF_REDIS_HOST=neutrino_ayakaleaf_redis",  # scan: allow
    "REDIS_HOST=neutrino_ayakaleaf_redis",
    "REDIS_PORT=6379",
    "V1_HISTORY_URL=http://127.0.0.1:3100/api",
    "GIT_BRIDGE_ENABLED=false",
    "EMAIL_CONFIRMATION_DISABLED=true",
    "DOCS_MCP_URL=",
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


def secrets_of(stored: dict) -> dict:
    return {
        name: opened(stored, f"{name}_sealed", f"device_ayakaleaf:{name}".encode())
        for name in ("secret", "password", "session_secret", "invite_secret")
    }


def test_the_first_install_generates_the_four_secrets_once_and_keeps_them(store):
    first = ayakaleaf.ensure_config(store, DEVICE)
    again = ayakaleaf.ensure_config(store, DEVICE)

    assert first == again == store.read(DEVICE, "ayakaleaf")
    assert set(first) == {
        "secret_sealed",
        "password_sealed",
        "session_secret_sealed",
        "invite_secret_sealed",
    }
    opened_values = list(secrets_of(first).values())
    assert all(len(value) >= 40 for value in opened_values)
    assert len(set(opened_values)) == 4


def test_the_install_keeps_the_model_beside_the_secrets(store):
    store.write(DEVICE, "ayakaleaf", {"model": "gpt-x"})

    written = ayakaleaf.ensure_config(store, DEVICE)

    assert written["model"] == "gpt-x"


def test_the_state_carries_two_secrets_opened_and_the_names(store):
    stored = ayakaleaf.ensure_config(store, DEVICE)

    config = ayakaleaf.agent_config(
        stored, DEVICE, local_name="ayakaleaf.argon.localhost"
    )

    opened_values = secrets_of(stored)
    assert config == {
        "secret": opened_values["secret"],
        "password": opened_values["password"],
        "cookie_name": "ayakaleaf_sid_dev-1",
        "local_name": "ayakaleaf.argon.localhost",
    }


def test_a_file_with_nothing_sealed_sends_empty_secrets():
    assert ayakaleaf.agent_config({}, DEVICE) == {
        "secret": "",
        "password": "",
        "cookie_name": "ayakaleaf_sid_dev-1",
        "local_name": "",
    }


def test_the_cookie_is_named_for_the_first_12_characters_of_the_device_id():
    assert ayakaleaf.cookie_name(DEVICE_ID) == "ayakaleaf_sid_a9cae9416662"


def test_the_three_containers_are_composed_as_the_module_s_page_lists_them(store):
    stored = ayakaleaf.ensure_config(store, DEVICE)
    key = ai_keys.ensure_module_key(store, DEVICE, "ayakaleaf", "argon")
    store.set_want(DEVICE, "ayakaleaf", "running")
    opened_values = secrets_of(stored)

    composed = compose_hub_containers(store, DEVICE, LINUX)

    shared = {
        "module": "ayakaleaf",
        "ports": [],
        "is_autostart": True,
        "services": [],
        "source_sets": ["ctan"],
    }
    assert composed == [
        {
            **shared,
            "name": "neutrino_ayakaleaf_mongo",
            "image": {"digest": MONGO_DIGEST, "sources": ["docker.io/library/mongo"]},
            "volumes": ["neutrino_ayakaleaf_mongo:/data/db"],
            "environment": [],
            "command": "--replSet overleaf",
            "after": [],
            "page_port": 0,
        },
        {
            **shared,
            "name": "neutrino_ayakaleaf_redis",
            "image": {"digest": REDIS_DIGEST, "sources": ["docker.io/library/redis"]},
            "volumes": ["neutrino_ayakaleaf_redis:/data"],
            "environment": [],
            "command": "redis-server --appendonly yes",
            "after": [],
            "page_port": 0,
        },
        {
            **shared,
            "name": "neutrino_ayakaleaf",
            "image": {"digest": APP_DIGEST, "sources": APP_SOURCES},
            "volumes": [
                "neutrino_ayakaleaf_data:/var/lib/overleaf",
                "neutrino_ayakaleaf_texlive:/usr/local/texlive",
            ],
            "environment": [
                *FIXED,
                f"OVERLEAF_SESSION_SECRET={opened_values['session_secret']}",
                f"OVERLEAF_INVITE_TOKEN_SECRET={opened_values['invite_secret']}",
                "COOKIE_NAME=ayakaleaf_sid_dev-1",
                "NEUTRINO_GATEWAY_URL=http://host.containers.internal:8317",
                f"NEUTRINO_GATEWAY_KEY={key}",
            ],
            "command": "",
            "after": ["neutrino_ayakaleaf_mongo", "neutrino_ayakaleaf_redis"],
            "page_port": 80,
            "stop_timeout_s": 60,
            "success_exit_codes": [2],
        },
    ]
    assert not any(
        opened_values["secret"] in line or opened_values["password"] in line
        for container in composed
        for line in container["environment"]
    )


def ai_lines(store, models) -> list:
    composed = compose_hub_containers(store, DEVICE, LINUX, models=models)
    app = next(item for item in composed if item["name"] == "neutrino_ayakaleaf")
    return [line for line in app["environment"] if line.startswith("AI_")]


def test_the_ai_variables_name_the_first_served_model_while_the_tab_names_none(store):
    ayakaleaf.ensure_config(store, DEVICE)
    key = ai_keys.ensure_module_key(store, DEVICE, "ayakaleaf", "argon")
    store.set_want(DEVICE, "ayakaleaf", "running")

    assert ai_lines(store, ["first-model", "second-model"]) == [
        "AI_ENABLED=true",
        "AI_BASE_URL=http://host.containers.internal:8317/v1",
        f"AI_API_KEY={key}",
        "AI_MODEL=first-model",
    ]
    assert ai_lines(store, []) == []


def test_the_tab_s_model_is_the_app_s_while_the_gateway_serves_one(store):
    ayakaleaf.ensure_config(store, DEVICE)
    ai_keys.ensure_module_key(store, DEVICE, "ayakaleaf", "argon")
    store.set_want(DEVICE, "ayakaleaf", "running")
    store.write(DEVICE, "ayakaleaf", {**store.read(DEVICE, "ayakaleaf"), "model": "m2"})

    assert "AI_MODEL=m2" in ai_lines(store, ["m1", "m2"])
    assert ai_lines(store, []) == []


def test_no_ai_variable_is_written_while_the_module_has_no_key(store):
    ayakaleaf.ensure_config(store, DEVICE)
    store.set_want(DEVICE, "ayakaleaf", "running")

    assert ai_lines(store, ["m1"]) == []


def test_no_container_is_composed_while_a_secret_does_not_open(store):
    store.set_want(DEVICE, "ayakaleaf", "running")

    assert compose_hub_containers(store, DEVICE, LINUX) == []

    stored = ayakaleaf.ensure_config(store, DEVICE)
    store.write(DEVICE, "ayakaleaf", {**stored, "invite_secret_sealed": {"x": 1}})

    assert compose_hub_containers(store, DEVICE, LINUX) == []


def test_the_chosen_model_reads_the_tab_then_the_first_served():
    assert ayakaleaf.chosen_model({"model": "b"}, ["a", "b"]) == "b"
    assert ayakaleaf.chosen_model({"model": ""}, ["a", "b"]) == "a"
    assert ayakaleaf.chosen_model({"model": "b"}, []) == ""


def test_every_entry_names_the_three_images_the_oci_feed_and_the_ctan_set():
    manifest = load_module_manifests()["ayakaleaf"]

    assert (manifest["license"], manifest["is_data_forward_only"]) == (
        "AGPL-3.0",
        True,
    )
    assert manifest["uninstall_data"]["is_deleted"] is True
    assert set(manifest["platforms"]) == {
        "linux",
        "windows-amd64",
        "darwin-arm64",
        "darwin-amd64",
    }
    for entry in manifest["platforms"].values():
        assert (entry["runner"], entry["install"]["method"]) == (
            "container",
            "container",
        )
        params = entry["install"]["params"]
        assert params["version"] == "6.3.2"
        assert params["source_sets"] == ["ctan"]
        assert params["releases"] == [
            {
                "kind": "oci",
                "sources": ["https://ghcr.io"],
                "repository": "ayaka-notes/overleaf-pro",
                "tag": "{version}",
            }
        ]
        assert params["artifacts"] == [
            {
                "name": "app",
                "kind": "image",
                "digest": APP_DIGEST,
                "sources": APP_SOURCES,
            },
            {
                "name": "mongo",
                "kind": "image",
                "digest": MONGO_DIGEST,
                "sources": ["docker.io/library/mongo"],
            },
            {
                "name": "redis",
                "kind": "image",
                "digest": REDIS_DIGEST,
                "sources": ["docker.io/library/redis"],
            },
        ]
