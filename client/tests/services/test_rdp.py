"""The desktop viewer: the hub is asked, the viewer dialed, nothing kept.

Connect asks the hub over the open socket for the share's address and
password, starts the carried viewer with ``--connect`` and ``--password``,
and the password lands in no log line and no state payload. Every viewer
opened is closed by ``close_all``.
"""

import json

import pytest

import neutrino_client.bundled as bundled
import neutrino_client.services.rdp as rdp_module
from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_client.services.rdp import (
    RdpViewerHandler,
    client_invocation,
    connect_peer,
)
from tests.conftest import SERVICES, FakeClientPlatform, FakeProcess

ENTRY = SERVICES[-1]
CONNECT_BODY = {"action": "connect", "id": "rdp_s9"}


class FakeHub:
    """The hub's answer to one ask, scripted."""

    def __init__(self, reply=None, error=None):
        self.reply = (
            reply
            if reply is not None
            else {
                "host": "192.168.100.6",
                "port": 21118,
                "password": "hunter2",  # scan: allow
            }
        )
        self.error = error
        self.asked = []

    def ask(self, kind, args):
        self.asked.append((kind, dict(args)))
        if self.error is not None:
            raise self.error
        return dict(self.reply)


def failure_of(subject) -> dict:
    """What the desktop lane refused last, as the state carries it."""
    work = subject.state()["rdp_work"]
    return {"code": work["code"], "params": work["params"]}


IDLE_WORK = {"state": "idle", "step": "", "code": "", "params": {}}


def run_inline(target):
    """The lane's thread starter, running the job right here."""
    target()


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(bundled, "rustdesk_path", lambda: "/opt/rustdesk")
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    lines = []
    platform = FakeClientPlatform()
    hub = FakeHub()
    subject = RdpViewerHandler(
        platform=platform, ask=hub.ask, log=lines.append, start_thread=run_inline
    )
    return subject, platform, hub, lines


def test_connect_asks_the_hub_and_dials_the_viewer(handler):
    subject, platform, hub, lines = handler

    outcome = subject.act(entries=[ENTRY], body=CONNECT_BODY)

    assert outcome == {}
    assert hub.asked == [("rdp_connect", {"service_id": "rdp_s9"})]
    (process,) = platform.started
    assert process.argv == [
        "/opt/rustdesk",
        "--connect",
        "192.168.100.6",
        "--password",
        "hunter2",  # scan: allow
    ]
    assert subject.state() == {
        "viewers": {"rdp_s9": {"is_running": True}},
        "rdp_work": IDLE_WORK,
    }


def test_the_password_reaches_no_log_and_no_state(handler):
    subject, _platform, _hub, lines = handler

    subject.act(entries=[ENTRY], body=CONNECT_BODY)

    assert "hunter2" not in "\n".join(lines)  # scan: allow
    assert "hunter2" not in json.dumps(subject.state())  # scan: allow
    assert "password" not in json.dumps(subject.state())


def test_another_port_is_spelled_out(handler):
    subject, platform, hub, _lines = handler
    hub.reply["port"] = 25000

    subject.act(entries=[ENTRY], body=CONNECT_BODY)

    assert platform.started[0].argv[2] == "192.168.100.6:25000"


def test_a_share_the_hub_no_longer_has_is_typed(handler):
    subject, platform, hub, _lines = handler
    hub.error = GatewayRefusedDetail(code="rdp_not_shared", params={})

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject) == {"code": "rdp_not_shared", "params": {}}
    assert platform.started == []


@pytest.mark.parametrize(
    "error, code",
    [
        (GatewayUnreachable("down"), "hub_unreachable"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (RuntimeError("no hub"), "hub_refused"),
    ],
)
def test_a_hub_that_does_not_answer_is_typed(handler, error, code):
    subject, platform, hub, _lines = handler
    hub.error = error

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject)["code"] == code
    assert platform.started == []


def test_a_missing_viewer_is_a_bundle_refusal(handler, monkeypatch):
    subject, platform, hub, _lines = handler
    monkeypatch.setattr(bundled, "rustdesk_path", lambda: "")

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject) == {
        "code": "bundle_missing",
        "params": {"binary": "rustdesk"},
    }
    assert hub.asked == []


def test_an_entry_nobody_published_is_refused(handler):
    subject, _platform, hub, _lines = handler

    refusal = subject.act(entries=[ENTRY], body={"action": "connect", "id": "x"})

    assert refusal == {"code": "unknown_request", "params": {}}
    assert hub.asked == []


def test_an_action_the_handler_does_not_know_is_typed(handler):
    subject, _platform, _hub, _lines = handler

    assert subject.act(entries=[ENTRY], body={"action": "share"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_a_reply_with_no_address_is_refused_rather_than_dialled(handler):
    subject, platform, hub, _lines = handler
    hub.reply["host"] = ""

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject) == {"code": "rdp_no_address", "params": {}}
    assert platform.started == []


def test_no_display_refuses_rather_than_opening_nothing(handler, monkeypatch):
    subject, platform, _hub, _lines = handler
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    monkeypatch.setattr(rdp_module.os, "environ", {})

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject) == {"code": "rdp_no_desktop", "params": {}}
    assert platform.started == []


@pytest.mark.parametrize("platform_name", ["darwin", "win32"])
def test_a_session_that_names_no_display_still_has_a_screen_off_linux(
    handler, monkeypatch, platform_name
):
    """macOS and Windows hand every process of a session its screen; only
    Linux says so in the environment."""
    subject, platform, _hub, _lines = handler
    monkeypatch.setattr(rdp_module.sys, "platform", platform_name)
    monkeypatch.setattr(rdp_module.os, "environ", {})

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject)["code"] == ""
    assert isinstance(platform.started[0], FakeProcess)


def test_a_viewer_that_will_not_start_is_typed(handler):
    subject, platform, _hub, _lines = handler
    platform.start_error = OSError("no such binary")

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}

    assert failure_of(subject)["code"] == "rdp_launch_failed"


def test_close_all_terminates_every_viewer_and_is_idempotent(handler):
    subject, platform, _hub, _lines = handler
    subject.act(entries=[ENTRY], body=CONNECT_BODY)
    second = dict(ENTRY, id="rdp_s10")
    subject.act(entries=[ENTRY, second], body={"action": "connect", "id": "rdp_s10"})

    subject.close_all()
    subject.release()

    assert all(process.is_terminated for process in platform.started)
    assert subject.state() == {"viewers": {}, "rdp_work": IDLE_WORK}


def test_a_viewer_the_person_closed_leaves_the_state(handler):
    subject, platform, _hub, _lines = handler
    subject.act(entries=[ENTRY], body=CONNECT_BODY)
    platform.started[0].returncode = 0

    assert subject.state() == {"viewers": {}, "rdp_work": IDLE_WORK}


def test_the_default_port_is_dialled_by_bare_address():
    assert connect_peer("192.168.100.6", 21118) == "192.168.100.6"
    assert connect_peer("192.168.100.6", 25000) == "192.168.100.6:25000"
    assert connect_peer("", 21118) == ""


def test_the_invocation_keeps_only_the_display_branch(monkeypatch):
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    monkeypatch.setattr(rdp_module.os, "environ", {"WAYLAND_DISPLAY": "wayland-0"})
    assert client_invocation("/r", "h", "p") == [
        "/r",
        "--connect",
        "h",
        "--password",
        "p",
    ]

    monkeypatch.setattr(rdp_module.os, "environ", {})
    with pytest.raises(LookupError):
        client_invocation("/r", "h", "p")

    monkeypatch.setattr(rdp_module.sys, "platform", "win32")
    assert client_invocation("/r", "h", "p")[1] == "--connect"

    import inspect

    assert "runuser" not in inspect.getsource(rdp_module)


def test_a_second_connect_while_one_is_in_flight_is_busy(monkeypatch):
    """The lane runs one connect at a time; the page greys the row."""
    monkeypatch.setattr(bundled, "rustdesk_path", lambda: "/opt/rustdesk")
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    held = []
    subject = RdpViewerHandler(
        platform=FakeClientPlatform(),
        ask=FakeHub().ask,
        log=print,
        start_thread=held.append,
    )

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert subject.state()["rdp_work"]["state"] == "working"
    assert subject.state()["rdp_work"]["step"] == "connecting:rdp_s9"
    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {
        "code": "busy",
        "params": {"step": "connecting:rdp_s9"},
    }

    held[0]()
    assert subject.state()["rdp_work"]["state"] == "idle"
