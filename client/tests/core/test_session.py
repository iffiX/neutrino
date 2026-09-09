"""The resident loop: the poll, its reply, the refusals, the shutdown.

Every poll carries the catalog hash and re-ships nothing when it matches;
the credential is adopted; a binding another process wrote is adopted; three
refusals unbind; ``is_disabled`` lets go of everything but the binding; the
shutdown runs its order once and is idempotent.
"""

import json

import pytest

import neutrino_client.core.channel as channel
from neutrino_client import CLIENT_VERSION
from neutrino_client.core.channel import (
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_client.core.session import ClientSession
from neutrino_client.services.base import ServiceTypeHandler
from tests.conftest import SERVICES, FakeClientPlatform, bind, discard

CATALOG = {"services": SERVICES}
CREDENTIAL = {
    "base_url": "http://hub:8080",
    "api_key": "key-1",  # scan: allow
    "model": "m1",
}


def answer_with(monkeypatch, replies):
    """Script the hub's poll answers, one per call, the last repeating."""
    posted = []
    queue = list(replies)

    def post(self, path, payload):
        posted.append((path, json.loads(json.dumps(payload))))
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return json.loads(json.dumps(answer))

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    return posted


def reply(**overrides):
    base = {
        "hub_version": "0.2.0",
        "is_disabled": False,
        "catalog_hash": "h1",
        "catalog": CATALOG,
        "ai": CREDENTIAL,
    }
    base.update(overrides)
    return base


class RecordingHandler(ServiceTypeHandler):
    """A handler that remembers when it was released."""

    def __init__(self, service_type: str, log: list):
        self.service_type = service_type
        self._log = log

    def act(self, *, entries, body):
        return {}

    def update_credential(self, credential) -> None:
        return None

    def release(self) -> None:
        self._log.append(self.service_type)


@pytest.fixture
def bound(config_path):
    bind(config_path, url="http://hub")
    return ClientSession(log=discard, platform=FakeClientPlatform())


def test_the_poll_carries_the_persons_facts_and_the_hash(bound, monkeypatch):
    posted = answer_with(monkeypatch, [reply()])

    bound.run_once()
    bound.run_once()

    first_path, first = posted[0]
    assert first_path == "/api/client/poll"
    assert set(first) == {"hostname", "platform", "client_version", "catalog_hash"}
    assert first["client_version"] == CLIENT_VERSION
    assert first["catalog_hash"] == ""
    assert posted[1][1]["catalog_hash"] == "h1"
    assert "accounts" not in first and "metrics" not in first


def test_a_matching_hash_ships_no_catalog_and_keeps_the_last(bound, monkeypatch):
    answer_with(monkeypatch, [reply(), reply(catalog=None)])

    bound.run_once()
    bound.run_once()

    assert [entry["id"] for entry in bound.service_entries()] == [
        entry["id"] for entry in SERVICES
    ]
    assert bound.hub_version() == "0.2.0"


def test_the_credential_is_adopted_and_handed_to_the_ai_handler(bound, monkeypatch):
    answer_with(monkeypatch, [reply()])
    seen = []
    bound._services["ai"].update_credential = seen.append

    bound.run_once()

    assert bound.ai_credential() == CREDENTIAL
    assert seen == [CREDENTIAL]


def test_a_reply_without_a_credential_clears_it(bound, monkeypatch):
    answer_with(monkeypatch, [reply(), reply(ai=None)])

    bound.run_once()
    bound.run_once()

    assert bound.ai_credential() == {}


def test_an_unreadable_reply_is_typed_and_never_fatal(bound, monkeypatch):
    answer_with(monkeypatch, [reply(catalog="not an object")])

    delay = bound.run_once()

    assert delay > 0
    assert bound.last_error()["code"] == "hub_reply_unreadable"


def test_a_broken_wire_backs_off_and_keeps_the_binding(bound, monkeypatch):
    answer_with(monkeypatch, [GatewayUnreachable("down")])

    delays = [bound.run_once() for _ in range(3)]

    assert delays == [5, 10, 20]
    assert bound.is_connected() is True
    assert bound.last_error()["code"] == "hub_unreachable"


@pytest.mark.parametrize(
    "error, cause",
    [
        (GatewayRefused("401"), "hub_refused"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (
            GatewayVersionRefused(hub_version="0.1.0", client_version="0.2.0"),
            "client_newer_than_hub",
        ),
    ],
)
def test_three_refusals_of_any_kind_unbind(
    bound, monkeypatch, config_path, error, cause
):
    answer_with(monkeypatch, [error])
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.run_once()
    bound.run_once()
    assert bound.is_connected() is True
    assert bound.last_error()["code"] == cause
    bound.run_once()

    assert bound.is_connected() is False
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert bound.last_error() == {"code": "self_unbound", "params": {"cause": cause}}
    assert released == ["ai", "file", "port", "rdp"]


def test_an_unreachable_poll_between_refusals_neither_counts_nor_resets(
    bound, monkeypatch
):
    answer_with(
        monkeypatch,
        [GatewayRefused("401"), GatewayUnreachable("down"), GatewayRefused("401")],
    )

    for _ in range(3):
        bound.run_once()

    assert bound.is_connected() is True
    assert bound._refusals == 2


def test_is_disabled_lets_go_of_everything_but_the_binding(
    bound, monkeypatch, config_path
):
    answer_with(monkeypatch, [reply(), reply(is_disabled=True)])
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.run_once()
    bound.run_once()

    assert bound.is_disabled() is True
    assert bound.is_connected() is True
    assert "gateway_url" in json.loads(config_path.read_text())
    assert bound.last_error() == {"code": "client_disabled", "params": {}}
    assert released == ["ai", "file", "port", "rdp"]
    assert bound.service_action("port", {"id": "svc_tcp", "is_enabled": True}) == {
        "code": "client_disabled",
        "params": {},
    }


def test_a_disabled_client_released_once_then_resumes(bound, monkeypatch):
    answer_with(
        monkeypatch,
        [reply(is_disabled=True), reply(is_disabled=True), reply(is_disabled=False)],
    )
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    for _ in range(3):
        bound.run_once()

    assert released == ["ai", "file", "port", "rdp"]
    assert bound.is_disabled() is False
    assert bound.last_error() is None


def test_an_external_binding_is_adopted_by_its_stamp(monkeypatch, config_path):
    session = ClientSession(log=discard, platform=FakeClientPlatform())
    assert session.is_connected() is False
    answer_with(monkeypatch, [reply()])

    bind(config_path, url="http://hub")
    session.run_once()

    assert session.is_connected() is True
    assert session.gateway_url() == "http://hub"


def test_an_external_disconnect_releases_everything(bound, monkeypatch, config_path):
    answer_with(monkeypatch, [reply()])
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)
    bound.run_once()

    config_path.write_text("{}")
    delay = bound.run_once()

    assert bound.is_connected() is False
    assert bound.service_entries() == []
    assert released == ["ai", "file", "port", "rdp"]
    assert delay == 2


def test_disconnect_tells_the_hub_first_and_lets_go(bound, monkeypatch, config_path):
    posted = answer_with(monkeypatch, [reply()])
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.disconnect()

    assert posted[-1][0] == "/api/client/leave"
    assert bound.is_connected() is False
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert released == ["ai", "file", "port", "rdp"]


def test_shutdown_runs_the_order_once_and_is_idempotent(bound):
    released = []
    for service_type in ("ai", "file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.shutdown()
    bound.shutdown()

    assert released == ["ai", "file", "port", "rdp"]


def test_shutdown_survives_a_handler_that_refuses(bound):
    released = []

    class Refusing(RecordingHandler):
        def release(self):
            raise OSError("busy")

    bound._services["ai"] = Refusing("ai", released)
    for service_type in ("file", "port", "rdp"):
        bound._services[service_type] = RecordingHandler(service_type, released)

    bound.shutdown()

    assert released == ["file", "port", "rdp"]


def test_the_state_carries_every_handlers_keys(bound):
    states = bound.service_states()

    assert set(states) >= {"forwards", "mounts", "ai", "ai_tool_configs", "viewers"}


def test_an_unknown_service_type_is_refused(bound):
    assert bound.service_action("nothing", {}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_show_reaches_the_registered_window(bound):
    shown = []
    bound.on_show = lambda: shown.append(1)

    bound.request_show()
    bound.on_show = None
    bound.request_show()

    assert shown == [1]


def test_post_without_a_binding_is_unreachable():
    session = ClientSession(log=discard, platform=FakeClientPlatform())

    with pytest.raises(GatewayUnreachable):
        session.post("/api/client/rdp_connect", {})
