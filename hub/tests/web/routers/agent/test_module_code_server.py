"""The code-server block: the instances, their secrets and the release.

What these pin: the view reads the release the machine reports, the
instances, each with what the machine reports of it, and the accounts; a
set is checked on the agent as the agent will receive it, each secret
opened; each instance's secret is sealed once per account and kept across
sets; two instances sharing an account or a port are refused by code
before the agent is asked; the state the agent is sent holds the opened
secret and never a seal, with the release the manifest pins for the
platform; and a token minted for an instance is its secret's, for 60
seconds and one nonce.
"""

import base64
import hashlib
import hmac
import json

import pytest

from neutrino_hub.modules.credentials.vault import unseal_bytes
from neutrino_hub.modules.devices.constants import DEVICE_CODE_SERVER_SECRET_AAD
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_code_server
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, module_box

BASE = "/api/agent/module/code_server"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
DARWIN = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(monkeypatch, tmp_path, module_code_server.router)
    with client:
        yield client, runtime


def stored(tmp_path) -> list:
    path = tmp_path / "devices" / DEVICE / "code_server.json"
    return json.loads(path.read_text())["instances"]


def test_the_view_reads_the_release_the_instances_and_the_accounts(api):
    client, runtime = api
    DesiredStateStore().write(
        DEVICE, "code_server", {"instances": [{"account": "alice", "port": 8443}]}
    )
    runtime.report(
        DEVICE,
        "code_server",
        state="running",
        version="4.140.0",
        instances=[
            {"account": "alice", "is_running": False, "code": "code_server_port_taken"}
        ],
    )
    runtime.device_accounts[DEVICE] = ["alice", "bob"]

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["version"] == "4.140.0"
    assert view["instances"] == [
        {
            "account": "alice",
            "port": 8443,
            "is_running": False,
            "code": "code_server_port_taken",
        }
    ]
    assert view["accounts"] == ["alice", "bob"]


def test_a_set_is_checked_as_the_agent_receives_it(api, tmp_path):
    client, runtime = api
    body = {"device_id": DEVICE, "instances": [{"account": "alice", "port": 8443}]}

    answer = client.post(f"{BASE}/set", json=body)

    assert answer.status_code == 200
    (instance,) = stored(tmp_path)
    assert set(instance) == {"account", "port", "secret_sealed"}
    _device, module, checked = runtime.agent_sessions.validations[0]
    assert module == "code_server"
    secret = unseal_bytes(
        instance["secret_sealed"], DEVICE_CODE_SERVER_SECRET_AAD
    ).decode()
    assert checked == {
        "instances": [{"account": "alice", "port": 8443, "secret": secret}]
    }
    assert len(secret) >= 32
    assert len(runtime.agent_sessions.pushes) == 1


def test_the_secret_is_made_once_and_kept(api, tmp_path):
    client, _runtime = api
    body = {"device_id": DEVICE, "instances": [{"account": "alice", "port": 8443}]}
    client.post(f"{BASE}/set", json=body)
    first = stored(tmp_path)[0]

    body["instances"].append({"account": "bob", "port": 8444})
    client.post(f"{BASE}/set", json=body)

    alice, bob = stored(tmp_path)
    assert alice["secret_sealed"] == first["secret_sealed"]
    assert bob["secret_sealed"] != alice["secret_sealed"]


@pytest.mark.parametrize(
    "instances, code",
    [
        (
            [{"account": "alice", "port": 8443}, {"account": "Alice", "port": 8444}],
            "account_duplicate",
        ),
        (
            [{"account": "alice", "port": 8443}, {"account": "bob", "port": 8443}],
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


@pytest.mark.parametrize(
    "platform, key", [(LINUX, "linux-amd64"), (DARWIN, "darwin-arm64")]
)
def test_the_state_carries_the_opened_secret_and_the_pinned_release(api, platform, key):
    client, _runtime = api
    client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": 8443}]},
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "code_server", "running")

    desired, _ = store.compose(DEVICE, platform)

    module = desired["modules"]["code_server"]
    (instance,) = module["config"]["instances"]
    assert set(instance) == {"account", "port", "secret"}
    assert module["install"]["kind"] == "code_server"
    assert module["install"]["package_kind"] == "tar"
    assert module["install"]["url"].endswith(
        f"code-server-4.140.0-{key.replace('darwin', 'macos')}.tar.gz"
    )
    assert "sealed" not in json.dumps(desired)


def test_a_token_is_the_instances_secret_signing_an_expiry_and_a_nonce(api):
    client, _runtime = api
    client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": 8443}]},
    )
    store = DesiredStateStore()
    store.set_want(DEVICE, "code_server", "running")
    secret = store.compose(DEVICE, LINUX)[0]["modules"]["code_server"]["config"][
        "instances"
    ][0]["secret"]

    first = store.code_server_token(DEVICE, "alice", now=1_800_000_000)
    second = store.code_server_token(DEVICE, "alice", now=1_800_000_000)

    raw = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))
    assert int.from_bytes(raw[:8], "big") == 1_800_000_060
    assert raw[24:] == hmac.new(secret.encode(), raw[:24], hashlib.sha256).digest()
    assert first != second
    assert store.code_server_token(DEVICE, "nobody") == ""
