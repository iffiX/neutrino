"""The desktop viewer: the service stream answers, the viewer dials the forward.

Connect opens the entry's ``service`` stream on its hub for the seat's
password, makes the entry's forward of the local port table, and starts the
carried viewer with ``--connect 127.0.0.1[:<local port>]`` and
``--password``; the viewer never dials the share's own address, and the
password lands in no log line and no state payload. The forward ends with
the viewer. Every viewer opened is closed by ``close_all``, and one hub's by
``release_hub``.
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
from neutrino_client.services.forward import (
    ForwardListenerRegistry,
    PortLocalTable,
    is_port_free,
)
from neutrino_client.services.rdp import (
    RdpViewerHandler,
    client_invocation,
    connect_peer,
)
from tests.conftest import (
    SERVICES,
    FakeClientPlatform,
    FakeConnectHub,
    FakeProcess,
    discard,
)

ENTRY = SERVICES[4]
OFFICE_ENTRY = SERVICES[-1]
CONNECT_BODY = {"action": "connect", "hub_id": "h1", "id": "rdp_s9"}


class FakeHub:
    """The close the hub answers a service stream with, scripted."""

    def __init__(self, reply=None, error=None):
        self.reply = (
            reply if reply is not None else {"password": "hunter2"}  # scan: allow
        )
        self.error = error
        self.opened = []

    def open_service(self, hub_id, entry_id):
        self.opened.append((hub_id, entry_id))
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


def forwards_on(busy=()):
    """A registry whose table finds every free port free but the busy ones."""
    return ForwardListenerRegistry(
        open_connect=FakeConnectHub().open_connect,
        ports=PortLocalTable(
            is_free=lambda port: port not in busy and is_port_free(port)
        ),
        log=discard,
    )


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(bundled, "rustdesk_path", lambda: "/opt/rustdesk")
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    lines = []
    platform = FakeClientPlatform()
    hub = FakeHub()
    forwards = forwards_on(busy=(21118,))
    subject = RdpViewerHandler(
        platform=platform,
        open_service=hub.open_service,
        forwards=forwards,
        log=lines.append,
        start_thread=run_inline,
    )
    subject.forwards = forwards
    yield subject, platform, hub, lines
    forwards.release()


def test_connect_opens_the_entrys_service_stream_and_dials_the_viewer(handler):
    subject, platform, hub, lines = handler

    outcome = subject.act(entries=[ENTRY], body=CONNECT_BODY)

    assert outcome == {}
    assert hub.opened == [("h1", "rdp_s9")]
    (process,) = platform.started
    port = subject.forwards.port_of("h1", "rdp_s9")
    assert port >= 20000
    assert process.argv == [
        "/opt/rustdesk",
        "--connect",
        f"127.0.0.1:{port}",
        "--password",
        "hunter2",  # scan: allow
    ]
    assert subject.state() == {
        "viewers": {"h1/rdp_s9": {"is_running": True}},
        "rdp_work": IDLE_WORK,
    }


def test_the_password_reaches_no_log_and_no_state(handler):
    subject, _platform, _hub, lines = handler

    subject.act(entries=[ENTRY], body=CONNECT_BODY)

    assert "hunter2" not in "\n".join(lines)  # scan: allow
    assert "hunter2" not in json.dumps(subject.state())  # scan: allow
    assert "password" not in json.dumps(subject.state())


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
    assert hub.opened == []


def test_an_entry_nobody_published_is_refused(handler):
    subject, _platform, hub, _lines = handler

    refusal = subject.act(
        entries=[ENTRY], body={"action": "connect", "hub_id": "h1", "id": "x"}
    )
    other_hub = subject.act(
        entries=[ENTRY], body={"action": "connect", "hub_id": "h2", "id": "rdp_s9"}
    )

    assert refusal == {"code": "unknown_request", "params": {}}
    assert other_hub == {"code": "unknown_request", "params": {}}
    assert hub.opened == []


def test_an_action_the_handler_does_not_know_is_typed(handler):
    subject, _platform, _hub, _lines = handler

    assert subject.act(entries=[ENTRY], body={"action": "share"}) == {
        "code": "unknown_request",
        "params": {},
    }


def test_a_forward_that_cannot_listen_starts_no_viewer(handler):
    subject, platform, _hub, _lines = handler
    subject.forwards.ports = PortLocalTable(is_free=lambda port: False)

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject)["code"] == "forward_failed"
    assert platform.started == []


def test_no_display_refuses_rather_than_opening_nothing(handler, monkeypatch):
    subject, platform, _hub, _lines = handler
    monkeypatch.setattr(rdp_module.sys, "platform", "linux")
    monkeypatch.setattr(rdp_module.os, "environ", {})

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert failure_of(subject) == {"code": "rdp_no_desktop", "params": {}}
    assert platform.started == []
    assert subject.forwards.forwards() == {}


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
    assert subject.forwards.forwards() == {}


def test_close_all_terminates_every_viewer_and_is_idempotent(handler):
    subject, platform, _hub, _lines = handler
    subject.act(entries=[ENTRY], body=CONNECT_BODY)
    second = dict(ENTRY, id="rdp_s10")
    subject.act(
        entries=[ENTRY, second],
        body={"action": "connect", "hub_id": "h1", "id": "rdp_s10"},
    )

    subject.close_all()
    subject.release()

    assert all(process.is_terminated for process in platform.started)
    assert subject.state() == {"viewers": {}, "rdp_work": IDLE_WORK}
    assert subject.forwards.forwards() == {}


def test_release_hub_closes_only_that_hubs_viewers(handler):
    subject, platform, hub, _lines = handler
    subject.act(entries=[ENTRY, OFFICE_ENTRY], body=CONNECT_BODY)
    subject.act(
        entries=[ENTRY, OFFICE_ENTRY],
        body={"action": "connect", "hub_id": "h2", "id": "rdp_lab"},
    )
    assert hub.opened == [("h1", "rdp_s9"), ("h2", "rdp_lab")]
    assert sorted(subject.state()["viewers"]) == ["h1/rdp_s9", "h2/rdp_lab"]

    assert subject.release_hub("h2") == 1
    assert subject.release_hub("h2") == 0

    home, office = platform.started
    assert office.is_terminated is True
    assert home.is_terminated is False
    assert list(subject.state()["viewers"]) == ["h1/rdp_s9"]
    assert list(subject.forwards.forwards()) == ["h1/rdp_s9"]


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
        open_service=FakeHub().open_service,
        forwards=forwards_on(busy=(21118,)),
        log=print,
        start_thread=held.append,
    )

    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {}
    assert subject.state()["rdp_work"]["state"] == "working"
    assert subject.state()["rdp_work"]["step"] == "connecting:h1/rdp_s9"
    assert subject.act(entries=[ENTRY], body=CONNECT_BODY) == {
        "code": "busy",
        "params": {"step": "connecting:h1/rdp_s9"},
    }

    held[0]()
    assert subject.state()["rdp_work"]["state"] == "idle"
    subject.release()


def test_a_viewer_that_ends_frees_the_entry_and_says_so(handler, monkeypatch):
    import threading
    import time

    from neutrino_client.services import rdp as rdp_module

    subject, platform, _, lines = handler
    monkeypatch.setattr(rdp_module, "RDP_WATCH_INTERVAL_S", 0.01)
    changed = threading.Event()
    subject._on_change = changed.set
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}
    subject.settle(2)
    (process,) = platform.started
    assert subject.state()["viewers"] != {}
    changed.clear()

    process.returncode = 0

    assert changed.wait(2)
    deadline = time.monotonic() + 2
    while (
        subject.state()["viewers"] or subject.forwards.forwards()
    ) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert subject.state()["viewers"] == {}
    assert any("closed" in line for line in lines)
    assert subject.forwards.forwards() == {}


def test_a_second_connect_while_the_viewer_runs_keeps_the_viewer_and_its_forward(
    handler, monkeypatch
):
    """The case seen on Windows: Connect again while the first viewer still
    shows its window. Nothing new starts, and the forward the first viewer
    dials stays."""
    import threading

    subject, platform, hub, _lines = handler
    monkeypatch.setattr(rdp_module, "RDP_WATCH_INTERVAL_S", 0.01)
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}
    port = subject.forwards.port_of("h1", "rdp_s9")

    again = subject.act(entries=SERVICES, body=CONNECT_BODY)
    threading.Event().wait(0.1)

    assert again == {"code": "rdp_viewer_open", "params": {}}
    assert len(platform.started) == 1
    assert hub.opened == [("h1", "rdp_s9")]
    assert subject.forwards.port_of("h1", "rdp_s9") == port
    assert subject.state()["viewers"] == {"h1/rdp_s9": {"is_running": True}}


def test_once_the_viewer_ends_a_connect_opens_a_new_one(handler):
    subject, platform, _hub, _lines = handler
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}
    platform.started[0].returncode = 0

    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}

    assert len(platform.started) == 2
    assert subject.state()["viewers"] == {"h1/rdp_s9": {"is_running": True}}


# --- a second viewer handed to the running viewer's window ---

OTHER_BODY = {"action": "connect", "hub_id": "h2", "id": OFFICE_ENTRY["id"]}


def wait_for(condition, timeout_s=3):
    import time

    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_a_second_viewer_handed_to_the_running_window_keeps_its_forward(
    handler, monkeypatch
):
    """Row 6a on Windows: B's launched process ends at once, its connection a
    tab in A's window; B's forward stays until A's window ends."""
    subject, platform, _hub, lines = handler
    monkeypatch.setattr(rdp_module, "RDP_WATCH_INTERVAL_S", 0.01)
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}
    assert subject.act(entries=SERVICES, body=OTHER_BODY) == {}
    first, second = platform.started
    b_key = f"h2/{OFFICE_ENTRY['id']}"

    second.returncode = 0

    assert wait_for(lambda: any("in the running viewer" in line for line in lines))
    assert subject.forwards.port_of("h2", OFFICE_ENTRY["id"])
    assert set(subject.state()["viewers"]) == {"h1/rdp_s9", b_key}
    assert subject.act(entries=SERVICES, body=OTHER_BODY) == {
        "code": "rdp_viewer_open",
        "params": {},
    }

    first.returncode = 0

    assert wait_for(lambda: subject.forwards.forwards() == {})
    assert subject.state()["viewers"] == {}


def test_a_viewer_closed_after_the_hand_off_window_ends_its_own_forward(
    handler, monkeypatch
):
    subject, platform, _hub, _lines = handler
    monkeypatch.setattr(rdp_module, "RDP_WATCH_INTERVAL_S", 0.01)
    monkeypatch.setattr(rdp_module, "RDP_HANDOFF_S", 0)
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}
    assert subject.act(entries=SERVICES, body=OTHER_BODY) == {}
    _first, second = platform.started

    second.returncode = 0

    assert wait_for(lambda: not subject.forwards.port_of("h2", OFFICE_ENTRY["id"]))
    assert set(subject.state()["viewers"]) == {"h1/rdp_s9"}


def test_a_lone_viewer_that_ends_early_ends_its_forward(handler, monkeypatch):
    subject, platform, _hub, _lines = handler
    monkeypatch.setattr(rdp_module, "RDP_WATCH_INTERVAL_S", 0.01)
    assert subject.act(entries=SERVICES, body=CONNECT_BODY) == {}

    platform.started[0].returncode = 0

    assert wait_for(lambda: subject.forwards.forwards() == {})
    assert subject.state()["viewers"] == {}
