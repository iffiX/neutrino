"""AstrBot on the hub: its file, the configuration the state sends, its container.

What these pin: the first install generates the token secret and the
dashboard's password once and keeps them, the password at least 8
characters with an upper-case letter, a lower-case letter and a digit; the
state carries ``{secret, password}`` opened, the forwarder's cookie name,
``neutrino_`` and the first 12 hex characters of the SHA-256 of the entry's
id, the app's local name, and the default model, empty while the gateway
serves none; the one hub container as the module's page lists it, its 6185
the page port, 6199 in ``local_ports``, SIGINT its stop signal, the
plugins' requirements in the volume and the gateway's address on a managed
machine and on the hub's own; no container while the password does not
open; and the manifest's four entries naming the tested image by digest,
the docker.io feed, the ``pypi`` set, its memory of 1024 MiB, its data
moving forward only and its visitors signed in as its one user.
"""

import hashlib

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.devices import astrbot
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.hub_containers import compose_hub_containers
from neutrino_hub.modules.devices.manifests import load_module_manifests
from tests.conftest import unlock_vault

DEVICE = "dev-1"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
DIGEST = "sha256:72f341f0ffcf6621ef820277642c5d63955f7beeac3683433ce09cac96379c78"
SOURCES = ["docker.io/soulter/astrbot", "m.daocloud.io/docker.io/soulter/astrbot"]
COOKIE_NAME = (
    "neutrino_" + hashlib.sha256(f"astrbot_{DEVICE}_web".encode()).hexdigest()[:12]
)


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
    first = astrbot.ensure_config(store, DEVICE)
    again = astrbot.ensure_config(store, DEVICE)

    assert first == again == store.read(DEVICE, "astrbot")
    assert set(first) == {"secret_sealed", "password_sealed"}
    secret = opened(first, "secret_sealed", b"device_astrbot:secret")
    password = opened(first, "password_sealed", b"device_astrbot:password")
    assert len(secret) >= 40 and len(password) >= 40 and secret != password
    assert astrbot.is_password_allowed(password)


@pytest.mark.parametrize(
    "password, is_allowed",
    [
        ("Abcdefg1", True),
        ("Abcdef1", False),
        ("abcdefg1", False),
        ("ABCDEFG1", False),
        ("Abcdefgh", False),
    ],
)
def test_a_password_astrbot_takes_has_eight_characters_upper_lower_and_a_digit(
    password, is_allowed
):
    assert astrbot.is_password_allowed(password) is is_allowed


def test_a_drawn_password_that_astrbot_refuses_is_drawn_again(monkeypatch):
    drawn = iter(["abcdefghijk", "ABCDEFGH1", "Good1password"])
    monkeypatch.setattr(astrbot.secrets, "token_urlsafe", lambda size: next(drawn))

    assert astrbot.new_password(32) == "Good1password"


def test_the_state_carries_both_secrets_opened_the_cookie_and_the_local_name(store):
    stored = astrbot.ensure_config(store, DEVICE)

    config = store.agent_config(DEVICE, "astrbot", stored, LINUX, machine_slug="argon")

    assert config == {
        "secret": opened(stored, "secret_sealed", b"device_astrbot:secret"),
        "password": opened(stored, "password_sealed", b"device_astrbot:password"),
        "cookie_name": COOKIE_NAME,
        "local_name": "astrbot.argon.localhost",
        "model": "",
    }


def test_the_state_carries_the_default_model_and_none_while_none_is_served(store):
    astrbot.ensure_config(store, DEVICE)
    store.set_want(DEVICE, "astrbot", "running")

    served, _ = store.compose(DEVICE, LINUX, ai_models=["m1", "m2"])
    none, _ = store.compose(DEVICE, LINUX, ai_models=[])

    assert served["modules"]["astrbot"]["config"]["model"] == "m1"
    assert none["modules"]["astrbot"]["config"]["model"] == ""


def test_a_machine_with_astrbot_reads_the_gateway_s_models_until_it_goes(store):
    assert not store.uses_gateway_models(DEVICE)
    store.set_want(DEVICE, "astrbot", "installed")
    assert store.uses_gateway_models(DEVICE)
    store.set_want(DEVICE, "astrbot", "absent")
    assert not store.uses_gateway_models(DEVICE)


def test_the_container_is_composed_as_the_module_s_page_lists_it(store):
    astrbot.ensure_config(store, DEVICE)
    key = ai_keys.ensure_module_key(store, DEVICE, "astrbot", "argon")
    store.set_want(DEVICE, "astrbot", "running")

    composed = compose_hub_containers(store, DEVICE, LINUX)

    assert composed == [
        {
            "module": "astrbot",
            "name": "neutrino_astrbot",
            "image": {"digest": DIGEST, "sources": SOURCES},
            "ports": [],
            "volumes": ["neutrino_astrbot_data:/AstrBot/data"],
            "environment": [
                "PIP_USER=1",
                "PYTHONUSERBASE=/AstrBot/data/python_user",  # scan: allow
                "NEUTRINO_GATEWAY_URL=http://host.containers.internal:8317",
                f"NEUTRINO_GATEWAY_KEY={key}",
            ],
            "command": "",
            "is_autostart": True,
            "services": [],
            "source_sets": ["pypi"],
            "after": [],
            "page_port": 6185,
            "local_ports": [6199],
            "stop_signal": "SIGINT",
        }
    ]


def test_on_the_hub_s_own_machine_the_container_reaches_the_gateway_s_own_port(
    store, config_dir
):
    (config_dir / "cliproxyapi").mkdir()
    (config_dir / "cliproxyapi" / "cliproxyapi.json").write_text(
        '{"listen_port": 8400}'
    )
    astrbot.ensure_config(store, DEVICE)
    store.set_want(DEVICE, "astrbot", "installed")

    (container,) = compose_hub_containers(store, DEVICE, LINUX, is_hub_machine=True)

    assert (
        "NEUTRINO_GATEWAY_URL=http://host.containers.internal:8400"
        in container["environment"]
    )
    assert container["is_autostart"] is False


def test_no_container_is_composed_while_the_password_does_not_open(store):
    store.set_want(DEVICE, "astrbot", "running")

    assert compose_hub_containers(store, DEVICE, LINUX) == []

    store.write(DEVICE, "astrbot", {"password_sealed": {"x": 1}})

    assert compose_hub_containers(store, DEVICE, LINUX) == []


def test_every_entry_names_the_tested_image_by_digest_the_feed_and_the_pypi_set():
    manifest = load_module_manifests()["astrbot"]

    assert manifest["memory_mib"] == 1024
    assert manifest["is_data_forward_only"] is True
    assert manifest["web_share"] == {"guest_login": "run_account"}
    assert manifest["uninstall_data"]["is_deleted"] is True
    assert set(manifest["platforms"]) == {
        "linux",
        "windows-amd64",
        "darwin-arm64",
        "darwin-amd64",
    }
    for entry in manifest["platforms"].values():
        assert entry["runner"] == "container"
        assert entry["requires"] == ["podman"]
        assert entry["install"]["method"] == "container"
        params = entry["install"]["params"]
        assert params["version"] == "4.29.4"
        assert params["source_sets"] == ["pypi"]
        assert params["releases"] == [
            {
                "kind": "oci",
                "sources": ["https://registry-1.docker.io"],
                "repository": "soulter/astrbot",
                "tag": "v{version}",
            }
        ]
        assert params["artifacts"] == [
            {"name": "astrbot", "kind": "image", "digest": DIGEST, "sources": SOURCES}
        ]
