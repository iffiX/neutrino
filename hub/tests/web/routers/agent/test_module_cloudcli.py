"""The CloudCLI block: the instances, their logins, their secrets and the device's key.

What these pin: the view reads the instances, each with its login and what
the machine reports of it, and the accounts; a set is checked on the agent
as the agent will receive it, both secrets opened, the gateway on the
hub's address in the device's network with the device's own key, and on
Windows each login's password; each instance's password and token secret
are sealed once per account and kept across sets; two instances sharing an
account or a port, a login the vault does not hold, and a Windows instance
with no login are refused by code before the agent is asked; the state the
agent is sent holds the opened secrets and never a seal or a login's id; a
token minted for an instance is its secret's, for 60 seconds and one
nonce; and withdrawing the module revokes the device's key.
"""

import base64
import hashlib
import hmac
import json

import pytest

from neutrino_hub.edition import EDITION
from neutrino_hub.modules.devices.constants import DEVICE_CLOUDCLI_NPM_REGISTRIES
from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.cliproxyapi.ops import load_config
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.constants import (
    DEVICE_CLOUDCLI_SECRET_AAD,
)
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.services.host_scope import HostScope
from neutrino_hub.web.routers.agent import module as device_modules
from neutrino_hub.web.routers.agent import module_cloudcli
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, module_box

BASE = "/api/agent/module/cloudcli"
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
HUB = "192.168.100.1"


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_keys, "_apply", lambda **kwargs: None)
    client, runtime = module_box(monkeypatch, tmp_path, module_cloudcli.router)
    runtime.device_scope[DEVICE] = HostScope(
        id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address=HUB
    )
    with client:
        yield client, runtime


def stored(tmp_path) -> list:
    path = tmp_path / "devices" / DEVICE / "cloudcli.json"
    return json.loads(path.read_text())["instances"]


def login(name: str) -> str:
    return (
        SecretVault()
        .add(
            kind="login", name=name, secret={"username": name, "password": f"pw-{name}"}
        )
        .id
    )


def opened(seal, aad) -> str:
    return unseal_bytes(seal, aad).decode()


def test_the_view_reads_the_instances_what_the_machine_says_and_the_accounts(api):
    client, runtime = api
    DesiredStateStore().write(
        DEVICE,
        "cloudcli",
        {"instances": [{"account": "alice", "port": 3001, "login_id": "l1"}]},
    )
    runtime.report(
        DEVICE,
        "cloudcli",
        state="running",
        instances=[
            {"account": "alice", "is_running": False, "code": "cloudcli_claude_missing"}
        ],
    )
    runtime.device_accounts[DEVICE] = ["alice", "bob"]

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["instances"] == [
        {
            "account": "alice",
            "port": 3001,
            "login_id": "l1",
            "is_running": False,
            "code": "cloudcli_claude_missing",
        }
    ]
    assert view["accounts"] == ["alice", "bob"]


def test_a_set_is_checked_as_the_agent_receives_it_with_the_devices_key(api, tmp_path):
    client, runtime = api
    body = {"device_id": DEVICE, "instances": [{"account": "alice", "port": 3001}]}

    answer = client.post(f"{BASE}/set", json=body)

    assert answer.status_code == 200
    held = load_config().device_keys[DEVICE]
    assert held.name == "device/box"
    (instance,) = stored(tmp_path)
    assert set(instance) == {
        "account",
        "port",
        "login_id",
        "web_password_sealed",
        "token_secret_sealed",
    }
    _device, module, checked = runtime.agent_sessions.validations[0]
    assert module == "cloudcli"
    assert checked == {
        "gateway_url": f"http://{HUB}:8317",
        "gateway_key": held.open_key(),
        "npm_registry": DEVICE_CLOUDCLI_NPM_REGISTRIES[EDITION],
        "instances": [
            {
                "account": "alice",
                "port": 3001,
                "web_password": opened(
                    instance["web_password_sealed"],
                    b"device_cloudcli:web_password",
                ),
                "token_secret": opened(
                    instance["token_secret_sealed"], DEVICE_CLOUDCLI_SECRET_AAD
                ),
            }
        ],
    }
    assert len(checked["instances"][0]["web_password"]) >= 32
    assert len(runtime.agent_sessions.pushes) == 1


def test_the_secrets_and_the_key_are_made_once_and_kept(api, tmp_path):
    client, _runtime = api
    body = {"device_id": DEVICE, "instances": [{"account": "alice", "port": 3001}]}
    client.post(f"{BASE}/set", json=body)
    first = stored(tmp_path)[0]
    key_id = load_config().device_keys[DEVICE].id

    body["instances"].append({"account": "bob", "port": 3002})
    client.post(f"{BASE}/set", json=body)

    alice, bob = stored(tmp_path)
    assert alice["web_password_sealed"] == first["web_password_sealed"]
    assert alice["token_secret_sealed"] == first["token_secret_sealed"]
    assert bob["token_secret_sealed"] != alice["token_secret_sealed"]
    assert load_config().device_keys[DEVICE].id == key_id


@pytest.mark.parametrize(
    "instances, code",
    [
        (
            [{"account": "alice", "port": 3001}, {"account": "Alice", "port": 3002}],
            "account_duplicate",
        ),
        (
            [{"account": "alice", "port": 3001}, {"account": "bob", "port": 3001}],
            "port_duplicate",
        ),
    ],
)
def test_two_instances_sharing_an_account_or_a_port_are_refused(api, instances, code):
    client, runtime = api

    answer = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "instances": instances}
    )

    assert (answer.status_code, answer.json()["detail"]["code"]) == (400, code)
    assert runtime.agent_sessions.validations == []


def test_a_windows_instance_needs_a_stored_login(api):
    client, runtime = api
    runtime.device_platform[DEVICE] = WINDOWS
    instance = {"account": "hanha", "port": 3001}

    missing = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "instances": [instance]}
    )
    unknown = client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{**instance, "login_id": "nope"}]},
    )
    taken = client.post(
        f"{BASE}/set",
        json={
            "device_id": DEVICE,
            "instances": [{**instance, "login_id": login("hanha")}],
        },
    )

    assert missing.json()["detail"] == {
        "code": "credential_missing",
        "params": {"account": "hanha"},
    }
    assert unknown.json()["detail"] == {
        "code": "unknown_credential",
        "params": {"field": "login_id"},
    }
    assert taken.status_code == 200
    (checked,) = runtime.agent_sessions.validations[0][2]["instances"]
    assert checked["password"] == "pw-hanha"


@pytest.mark.parametrize("platform, has_password", [(WINDOWS, True), (LINUX, False)])
def test_the_state_carries_the_opened_secrets_and_never_a_seal(
    api, platform, has_password
):
    client, runtime = api
    runtime.device_platform[DEVICE] = WINDOWS
    client.post(
        f"{BASE}/set",
        json={
            "device_id": DEVICE,
            "instances": [
                {"account": "hanha", "port": 3001, "login_id": login("hanha")}
            ],
        },
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "cloudcli", "running")

    desired, _ = store.compose(DEVICE, platform, hub_address=HUB)

    module = desired["modules"]["cloudcli"]
    (instance,) = module["config"]["instances"]
    assert set(instance) == {"account", "port", "web_password", "token_secret"} | (
        {"password"} if has_password else set()
    )
    assert module["config"]["gateway_url"] == f"http://{HUB}:8317"
    assert module["install"]["kind"] == "cloudcli"
    assert module["install"]["package_kind"] == ("zip" if has_password else "tar")
    assert "sealed" not in json.dumps(desired)


def test_a_token_is_the_instances_secret_signing_an_expiry_and_a_nonce(api):
    client, _runtime = api
    client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": 3001}]},
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "cloudcli", "running")
    secret = store.compose(DEVICE, LINUX)[0]["modules"]["cloudcli"]["config"][
        "instances"
    ][0]["token_secret"]

    first = store.cloudcli_token(DEVICE, "alice", now=1_800_000_000)
    second = store.cloudcli_token(DEVICE, "alice", now=1_800_000_000)

    raw = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))
    assert int.from_bytes(raw[:8], "big") == 1_800_000_060
    assert raw[24:] == hmac.new(secret.encode(), raw[:24], hashlib.sha256).digest()
    assert first != second
    assert store.cloudcli_token(DEVICE, "nobody") == ""


def test_withdrawing_the_module_revokes_the_devices_key(api, monkeypatch):
    client, runtime = api
    client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": 3001}]},
    )
    assert DEVICE in load_config().device_keys
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {"cloudcli": {"installer": "hub", "platforms": {}}},
    )

    device_modules._set_want(
        runtime,
        device_modules.DeviceModuleRequest(device_id=DEVICE, module="cloudcli"),
        "absent",
    )

    assert DEVICE not in load_config().device_keys
    assert ai_keys.device_gateway(DEVICE, HUB) == {"gateway_url": "", "gateway_key": ""}
