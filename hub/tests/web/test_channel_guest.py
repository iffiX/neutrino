"""A Web share's visitors on the hub's local channel, against a fake transport.

What these pin, by transport.md's "The guest path" and "The hub's local
channel" and protocol.md's "Web shares": each new control connection is
sent ``shares_set`` with the live shares' pairs; the ``guest`` question
admits a live share's ticket under its ufrag and refuses anything else
``share_unknown``, or by protocol number; a guest's ``hello`` is welcomed
with no state and counted online until its session ends; a hello for a
share that ended is closed ``share_unknown``; a visitor's ``connect`` and
``service`` are judged in the order of the codes; and the material follows
the entry's ``guest_login``.
"""

import asyncio
import base64
import hashlib
import hmac
import time

import pytest

from neutrino_hub.modules.clients.web_shares import WebShareRegistry, make_share
from neutrino_hub.modules.devices.module_table import (
    DEVICE_MODULE_ROWS,
    DeviceModuleRow,
)
from neutrino_hub.web import channel_guest, web_share_access
from neutrino_hub.web.web_share_access import WebShareGuestSessions
from tests.conftest import unlock_vault
from tests.web.test_local_channel import (  # noqa: F401 - the fixtures are used
    FakeRuntime,
    bound_device,
    config,
    recorded,
    started,
    stopped,
)

MANIFESTS = {
    "ayakaleaf": {"web_share": {"guest_login": "guest_account"}},
    "code_server": {"web_share": {"guest_login": "run_account"}},
}


class GuestPublished:
    """The published list with one Ayakaleaf, one code-server and one declared app."""

    def __init__(self, device_id):
        self.device_id = device_id
        self.listed = [
            {
                "id": "ayakaleaf_web",
                "app_id": "ayakaleaf",
                "type": "web",
                "source": "module",
                "description_code": "ayakaleaf_module",
                "description_params": {},
                "payload": {"url": "http://192.168.100.7:8900/"},
                "device_id": device_id,
            },
            {
                "id": "code_web",
                "app_id": "code",
                "type": "web",
                "source": "module",
                "description_code": "code_server_module",
                "description_params": {"account": "alice"},
                "payload": {"url": "http://192.168.100.7:8901/"},
                "device_id": device_id,
            },
            {
                "id": "nas_web",
                "app_id": "nas",
                "type": "web",
                "source": "declared",
                "description_code": "declared",
                "description_params": {},
                "payload": {"url": "http://192.168.100.9:5000/"},
                "host": "192.168.100.9",
                "device_id": "",
            },
        ]

    def entries(self):
        return list(self.listed), "f"

    def apps(self):
        return []


class TokenStates:
    """The desired states as the run_account material reaches for them."""

    def instance_token(self, key, module, account):
        return f"instance:{module}:{account}"

    def module_token(self, key, module):
        return f"module:{module}"


@pytest.fixture
def guests(config, monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(channel_guest, "load_module_manifests", lambda: MANIFESTS)
    monkeypatch.setattr(
        web_share_access,
        "DEVICE_MODULE_ROWS",
        DEVICE_MODULE_ROWS
        + (
            DeviceModuleRow(
                name="ayakaleaf",
                kind="container",
                config_file="ayakaleaf.json",
                description_code="ayakaleaf_module",
            ),
        ),
    )


def guest_runtime(tmp_path, device_id):
    runtime = FakeRuntime(tmp_path)
    runtime.web_share_guests = WebShareGuestSessions()
    runtime.published_services = GuestPublished(device_id)
    runtime.desired_states = TokenStates()
    return runtime


def stored(entry_id, *, device_id, module="", is_guest=False, days=7, now=None):
    share, secrets = make_share(
        name="share",
        app_id=entry_id.removesuffix("_web"),
        app_title="App",
        entry_id=entry_id,
        device_id=device_id,
        module=module,
        days=days,
        taken_accounts=set(),
        is_guest=is_guest,
        now=now,
    )
    WebShareRegistry().add(share)
    return share, secrets


async def admitted_guest(fake, share_id, session="g1"):
    await fake.event(
        "session_open",
        session=session,
        binding_id=share_id,
        role="guest",
        address="198.51.100.4",
        listener="main",
    )
    await fake.frame(
        session,
        {
            "type": "hello",
            "protocol": 4,
            "role": "guest",
            "id": share_id,
            "name": "guest",
            "software": "neutrino_share_page/1",
        },
    )


def test_a_new_control_connection_is_sent_the_live_pairs(
    guests, recorded, config, tmp_path
):
    share, secrets = stored("nas_web", device_id="")
    stored("nas_web", device_id="", days=1, now=time.time() - 2 * 86400)

    async def scenario():
        runtime = guest_runtime(tmp_path, "")
        fake, channel, task = await started(tmp_path, runtime)
        try:
            return await fake.next_command()
        finally:
            await stopped(fake, channel, task)

    command = asyncio.run(scenario())
    assert command["command"] == "shares_set"
    assert command["shares"] == [{"ufrag": share.ufrag, "pwd": secrets.pwd}]


def test_the_guest_question_admits_a_live_shares_ticket_alone(
    guests, recorded, config, tmp_path
):
    share, secrets = stored("nas_web", device_id="")
    gone, gone_secrets = stored(
        "nas_web", device_id="", days=1, now=time.time() - 2 * 86400
    )

    async def scenario():
        runtime = guest_runtime(tmp_path, "")
        fake, channel, task = await started(tmp_path, runtime)

        async def asked(ufrag, ticket, protocol=4):
            return await fake.ask(
                "guest",
                ticket=ticket,
                share=ufrag,
                protocol=protocol,
                address="198.51.100.4",
                listener="main",
            )

        try:
            return (
                await asked(share.ufrag, secrets.ticket),
                await asked(share.ufrag, gone_secrets.ticket),
                await asked("0" * 24, secrets.ticket),
                await asked(gone.ufrag, gone_secrets.ticket),
                await asked(share.ufrag, secrets.ticket, protocol=3),
            )
        finally:
            await stopped(fake, channel, task)

    good, wrong_ticket, unknown, expired, old = asyncio.run(scenario())
    assert good == {"binding_id": share.id}
    unknown_share = {"code": "share_unknown", "params": {}}
    assert wrong_ticket == unknown_share and unknown == unknown_share
    assert expired == unknown_share
    assert old == {
        "code": "protocol_too_old",
        "params": {"peer": 3, "hub": 4, "min": 4},
    }


def test_a_guest_is_welcomed_with_no_state_and_counted_until_its_end(
    guests, recorded, config, tmp_path
):
    share, _ = stored("nas_web", device_id="")

    async def scenario():
        runtime = guest_runtime(tmp_path, "")
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await fake.next_command()
            await admitted_guest(fake, share.id)
            welcome = await fake.next_frame()
            online = runtime.web_share_guests.count(share.id)
            await fake.event("session_end", session="g1", reason="peer_closed")
            await asyncio.sleep(0.2)
            after = runtime.web_share_guests.count(share.id)
            extra = list(fake.frames)
        finally:
            await stopped(fake, channel, task)
        return welcome, online, after, extra

    welcome, online, after, extra = asyncio.run(scenario())
    assert welcome["frame"]["type"] == "welcome" and welcome["session"] == "g1"
    assert online == 1 and after == 0
    assert extra == []


def test_a_hello_for_an_ended_share_is_closed_share_unknown(
    guests, recorded, config, tmp_path
):
    async def scenario():
        runtime = guest_runtime(tmp_path, "")
        fake, channel, task = await started(tmp_path, runtime)
        try:
            await fake.next_command()
            await admitted_guest(fake, "f" * 32)
            return await fake.next_command()
        finally:
            await stopped(fake, channel, task)

    command = asyncio.run(scenario())
    assert command["command"] == "session_close"
    assert command["code"] == "share_unknown" and command["session"] == "g1"


def test_a_visitors_streams_and_material_are_judged_in_order(
    guests, recorded, config, tmp_path
):
    device_id = bound_device(config)
    ayakaleaf, _ = stored(
        "ayakaleaf_web", device_id=device_id, module="ayakaleaf", is_guest=True
    )
    code, _ = stored("code_web", device_id=device_id, module="code_server")
    nas, _ = stored("nas_web", device_id="")

    async def scenario():
        runtime = guest_runtime(tmp_path, device_id)
        fake, channel, task = await started(tmp_path, runtime)
        answers = {}
        try:
            await fake.next_command()
            for session, share in (("ga", ayakaleaf), ("gc", code), ("gn", nas)):
                await admitted_guest(fake, share.id, session=session)
                await fake.next_frame()

            async def entry(session, open_body):
                return await fake.ask(
                    "entry", session=session, binding_id="", open=open_body
                )

            async def token(session, frame):
                return await fake.ask(
                    "token", session=session, binding_id="", frame=frame
                )

            answers["offline"] = await entry(
                "gc", {"kind": "connect", "id": "code_web"}
            )
            answers["other"] = await entry("gc", {"kind": "connect", "id": "nas_web"})
            answers["panel"] = await token("gc", {"request": "r", "is_panel": True})
            answers["shell"] = await entry("gc", {"kind": "shell", "device_id": "x"})
            answers["declared"] = await entry(
                "gn", {"kind": "connect", "id": "nas_web"}
            )
            answers["app"] = await token("gn", {"request": "r", "id": "nas_web"})
            runtime.agent_sessions.is_online = lambda key: True
            runtime.agent_sessions.get = lambda key: type(
                "Agent", (), {"session_id": "agent-s"}
            )()
            answers["agent"] = await entry("gc", {"kind": "connect", "id": "code_web"})
            answers["run"] = await token("gc", {"request": "r", "id": "code_web"})
            answers["preparing"] = await token(
                "ga", {"request": "r", "id": "ayakaleaf_web"}
            )
            runtime.agent_sessions.reports = lambda: {
                device_id: {
                    "modules": {
                        "ayakaleaf": {
                            "details": {
                                "guests": [
                                    {"account": ayakaleaf.guest.account, "code": ""}
                                ]
                            }
                        }
                    }
                }
            }
            answers["guest"] = await token(
                "ga", {"request": "r", "id": "ayakaleaf_web"}
            )
            runtime.published_services.listed = []
            answers["unpublished"] = await entry(
                "gc", {"kind": "connect", "id": "code_web"}
            )
            WebShareRegistry().remove_where(lambda share: True)
            answers["ended"] = await entry("gc", {"kind": "connect", "id": "code_web"})
        finally:
            await stopped(fake, channel, task)
        return answers

    answers = asyncio.run(scenario())
    assert answers["offline"] == {
        "code": "agent_offline",
        "params": {"device": device_id},
    }
    assert answers["other"] == {"code": "permission_denied", "params": {"kind": "web"}}
    assert answers["panel"] == {
        "code": "permission_denied",
        "params": {"kind": "panel"},
    }
    assert answers["shell"] == {"code": "kind_unknown", "params": {"kind": "shell"}}
    assert answers["declared"] == {
        "kind": "web",
        "device_id": "",
        "key": "",
        "target": {"address": "192.168.100.9", "port": 5000, "protocol": "tcp"},
    }
    assert answers["app"] == {"params": {}}
    assert answers["agent"] == {
        "kind": "web",
        "device_id": device_id,
        "key": "",
        "target": {
            "session": "agent-s",
            "open": {"kind": "connect", "port": 8901, "protocol": "tcp"},
        },
    }
    assert answers["run"] == {"params": {"token": "instance:code_server:alice"}}
    assert answers["preparing"] == {
        "code": "service_unknown",
        "params": {"service_id": "ayakaleaf_web"},
    }
    minted = answers["guest"]["params"]["token"]
    secret = ayakaleaf.guest.opened()["secret"]
    raw = base64.urlsafe_b64decode(minted + "=" * (-len(minted) % 4))
    expiry, nonce, mac = raw[:8], raw[8:24], raw[24:]
    assert int.from_bytes(expiry, "big") <= time.time() + 61
    assert hmac.compare_digest(
        mac, hmac.new(secret.encode(), expiry + nonce, hashlib.sha256).digest()
    )
    assert answers["unpublished"] == {
        "code": "service_unknown",
        "params": {"service_id": "code_web"},
    }
    assert answers["ended"] == {"code": "share_unknown", "params": {}}
