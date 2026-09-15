"""The hub's state: kept root-only, made true in one order, hashed honestly.

What these pin: the fixed module order, what each ``want`` does to a
module (absent uninstalls and clears the mark, installed puts the software
there and nothing else, stopped and running install what is missing then
configure and settle the unit, with the mark written on the first apply
that took), a module the state does not mention untouched, an install's
bytes asked for down a ``package {module}`` stream and its output sent up
a ``log {module}`` stream closed with the module's state, the applied
hash moving only when every mentioned module applied, a failed state
reported under the old hash and tried again only under another hash
unless the socket caused it, the first failure naming the state error,
the file's mode, and the latest state winning when several arrive.
"""

import json
import os
import stat
import threading

import pytest

from neutrino_agent.core.desired_state import (
    APPLY_ORDER,
    DesiredStateApplier,
    DesiredStateStore,
)
from neutrino_agent.exceptions import GatewayUnreachable, ModuleApplyError
from tests.streams.fake_channel import FakeChannel

INSTALL = {"kind": "system_package", "packages": ["x"], "verify": ""}


# The module whose recipe installs from bytes; the rest install by name.
BYTE_MODULES = ("gitea",)


class FakeEngine:
    """Observes a scripted set of installed modules and records the rest."""

    def __init__(self, names, *, absent=(), install_refusal=None):
        self.names = list(names)
        self.installed = {name for name in names if name not in absent}
        self.configured: set = set()
        self.states: list = []
        self.results: dict = {}
        self.refreshes = 0
        self.installs: list = []
        self.uninstalls: list = []
        self.install_refusal = install_refusal

    def take_state(self, modules):
        self.states.append(modules)

    def is_installed(self, name):
        return name in self.installed

    def is_configured(self, name):
        return name in self.configured

    def mark_configured(self, name):
        self.configured.add(name)

    def clear_configured(self, name):
        self.configured.discard(name)

    def record_apply(self, name, code, params):
        self.results[name] = (code, dict(params))

    def refresh_now(self):
        self.refreshes += 1

    def report(self):
        return {
            name: {"state": "installed" if name in self.installed else "absent"}
            for name in self.names
        }

    def install(self, name, *, receive, on_line=None):
        received = receive(name) if name in BYTE_MODULES else {}
        self.installs.append((name, received))
        if on_line is not None:
            on_line(f"{name}: installing")
        if "code" in received:
            return received
        if self.install_refusal is not None:
            return dict(self.install_refusal)
        self.installed.add(name)
        return {}

    def uninstall(self, name, *, on_line=None):
        self.uninstalls.append(name)
        if on_line is not None:
            on_line(f"{name}: uninstalling")
        self.installed.discard(name)
        self.configured.discard(name)
        return {}


class FakeShareHost:
    """A desktop host that records the seat passwords it was handed."""

    def __init__(self, refusal=None):
        self.passwords: list = []
        self.refusal = refusal

    def apply_seat_password(self, password):
        self.passwords.append(password)
        return dict(self.refusal) if self.refusal else {}


class FakeRunner:
    """A runner that records the verbs it is asked, and refuses on cue."""

    def __init__(self, *, failure=None, journal=None):
        self.failure = failure
        self.journal = journal if journal is not None else []
        self.applied: list = []
        self.stops = 0

    def apply(self, config):
        if self.failure is not None:
            raise self.failure
        self.applied.append(config)
        self.journal.append(("apply", id(self)))

    def stop(self):
        self.stops += 1
        self.journal.append(("stop", id(self)))


class FakeSocket:
    """Opens channels the way the session would, and keeps them."""

    def __init__(self):
        self.opened: list = []
        self.channels: list = []
        self.next_id = 1

    def __call__(self, kind, **args):
        self.opened.append((kind, args))
        channel = FakeChannel(stream_id=self.next_id)
        self.next_id += 2
        self.channels.append(channel)
        return channel


def state(state_hash: str = "h1", **wants) -> dict:
    """One state document naming each module with its want."""
    return {
        "hash": state_hash,
        "modules": {
            name: {
                "want": want,
                "config": {"n": name},
                "install": dict(INSTALL),
                "uninstall": {"packages": ["x"], "is_data_kept": True},
            }
            for name, want in wants.items()
        },
        "desktop": {"seat_password": ""},
    }


def applier(runners, engine=None, tmp_path=None, rdp=None, open_stream=None):
    engine = engine if engine is not None else FakeEngine(runners)
    held = DesiredStateApplier.__new__(DesiredStateApplier)
    held._engine = engine
    held._runners = dict(runners)
    held._store = DesiredStateStore(path=str(tmp_path / "desired.json"))
    held._rdp = rdp
    held._log = lambda message: None
    held._open_stream = open_stream
    held._package_dir = str(tmp_path / "packages")
    held._lock = threading.Lock()
    held._idle = threading.Condition(held._lock)
    held._is_applying = False
    held._pending = None
    held._applied_hash = ""
    held._tried_hash = ""
    held._state_error = None
    held._wakeup = threading.Event()
    return held, engine


def drive_once(held) -> None:
    """One turn of the worker's own loop, in this thread."""
    with held._lock:
        pending = held._pending
        held._pending = None
        tried = held._tried_hash
    if pending is None:
        return
    if pending.get("hash") and pending["hash"] == tried:
        return
    held.apply(pending)


# --- the store ---


def test_the_file_is_written_root_only_and_reads_back(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "agent/desired.json"))

    store.write({"hash": "h1", "modules": {}})

    mode = stat.S_IMODE(os.stat(tmp_path / "agent/desired.json").st_mode)
    assert mode == 0o600
    assert store.read() == {"hash": "h1", "modules": {}}


def test_a_missing_or_broken_file_reads_as_nothing(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "desired.json"))
    assert store.read() == {}

    (tmp_path / "desired.json").write_text("not json")
    assert store.read() == {}


# --- the order and the four wants ---


def test_modules_apply_in_the_fixed_order(tmp_path):
    journal: list = []
    runners = {name: FakeRunner(journal=journal) for name in reversed(APPLY_ORDER)}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(**{name: "running" for name in APPLY_ORDER}))

    assert [id(runners[name]) for name in APPLY_ORDER] == [
        entry[1] for entry in journal
    ]
    assert all(entry[0] == "apply" for entry in journal)
    assert engine.states[0].keys() == set(APPLY_ORDER)


def test_installed_puts_the_software_there_and_nothing_else(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="installed"))

    assert [name for name, _ in engine.installs] == ["samba"]
    assert runners["samba"].applied == []
    assert runners["samba"].stops == 0
    assert engine.configured == set()
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_running_installs_what_is_missing_configures_and_writes_the_mark(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert [name for name, _ in engine.installs] == ["samba"]
    assert runners["samba"].applied == [{"n": "samba"}]
    assert runners["samba"].stops == 0
    assert engine.configured == {"samba"}
    assert held.applied_hash == "h1"


def test_running_on_software_that_is_there_installs_nothing(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert engine.installs == []
    assert runners["samba"].applied == [{"n": "samba"}]
    assert engine.configured == {"samba"}


def test_stopped_configures_then_stops_the_unit(tmp_path):
    journal: list = []
    runners = {"samba": FakeRunner(journal=journal)}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="stopped"))

    assert runners["samba"].applied == [{"n": "samba"}]
    assert [entry[0] for entry in journal] == ["apply", "stop"]
    assert engine.configured == {"samba"}
    assert held.applied_hash == "h1"


def test_absent_uninstalls_what_is_there_and_touches_the_configuration_never(
    tmp_path,
):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)
    engine.configured.add("samba")

    held.apply(state(samba="absent"))

    assert engine.uninstalls == ["samba"]
    assert runners["samba"].applied == []
    assert engine.configured == set()
    assert "samba" not in engine.installed
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_absent_on_software_that_is_not_there_only_clears_the_mark(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    engine.configured.add("samba")
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="absent"))

    assert engine.uninstalls == []
    assert engine.configured == set()
    assert held.applied_hash == "h1"


def test_a_module_the_state_does_not_mention_is_untouched(tmp_path):
    runners = {"samba": FakeRunner(), "gitea": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert runners["gitea"].applied == []
    assert runners["gitea"].stops == 0
    assert engine.installs == []
    assert "gitea" not in engine.results
    assert held.applied_hash == "h1"


def test_a_want_outside_the_four_is_left_alone(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="reticulated"))

    assert runners["samba"].applied == []
    assert engine.installs == []
    assert held.applied_hash == "h1"


def test_a_failed_apply_writes_no_mark(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("samba_missing"))}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert engine.configured == set()
    assert held.state_error["code"] == "samba_missing"


def test_the_engine_observes_against_the_state_before_anything_applies(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert engine.states == [
        {
            "samba": {
                "want": "running",
                "config": {"n": "samba"},
                "install": INSTALL,
                "uninstall": {"packages": ["x"], "is_data_kept": True},
            }
        }
    ]
    assert engine.refreshes == 1


# --- the streams an install and an uninstall ride ---


def test_an_installs_output_goes_up_a_log_stream_closed_with_the_state(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    socket = FakeSocket()
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)

    held.apply(state(samba="running"))

    assert socket.opened == [("log", {"module": "samba"})]
    (log,) = socket.channels
    assert log.sent == [b"samba: installing\n"]
    assert log.closed == {"code": "", "params": {"state": "installed"}}


def test_a_failed_install_closes_the_log_with_its_code_and_fails_the_state(
    tmp_path,
):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(
        runners,
        absent=("samba",),
        install_refusal={"code": "install_unconfirmed", "params": {}},
    )
    socket = FakeSocket()
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)

    held.apply(state(samba="running"))

    (log,) = socket.channels
    assert log.closed == {
        "code": "install_unconfirmed",
        "params": {"state": "absent"},
    }
    assert runners["samba"].applied == []
    assert held.applied_hash == ""
    assert held.state_error == {
        "code": "install_unconfirmed",
        "params": {"module": "samba"},
    }
    assert engine.results["samba"] == ("install_unconfirmed", {})


def test_an_uninstalls_output_goes_up_a_log_stream_too(tmp_path):
    runners = {"samba": FakeRunner()}
    socket = FakeSocket()
    held, engine = applier(runners, tmp_path=tmp_path, open_stream=socket)

    held.apply(state(samba="absent"))

    assert socket.opened == [("log", {"module": "samba"})]
    (log,) = socket.channels
    assert log.sent == [b"samba: uninstalling\n"]
    assert log.closed == {"code": "", "params": {"state": "absent"}}


def test_the_bytes_come_down_a_package_stream_the_applier_opens(tmp_path):
    import hashlib

    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    socket = FakeSocket()
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=socket)
    channel = FakeChannel(stream_id=3)
    channel.feed(("data", b"gitea binary"))
    channel.feed(("close", "", {"sha256": hashlib.sha256(b"gitea binary").hexdigest()}))
    socket.channels.append(channel)

    def open_stream(kind, **args):
        if kind == "package":
            socket.opened.append((kind, args))
            return channel
        return socket(kind, **args)

    held._open_stream = open_stream

    held.apply(state(gitea="installed"))

    assert socket.opened == [
        ("log", {"module": "gitea"}),
        ("package", {"module": "gitea"}),
    ]
    name, received = engine.installs[0]
    assert name == "gitea"
    assert received["path"].startswith(str(tmp_path / "packages"))
    assert channel.credits[0] > 0
    assert held.applied_hash == "h1"


def test_without_a_socket_the_bytes_cannot_come_and_the_next_state_tries_again(
    tmp_path,
):
    """A dropped socket made nothing about the machine fail: the state is
    not latched, so the hub's next push of the same hash runs it."""
    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(gitea="installed"))

    assert engine.installs == [("gitea", {"code": "hub_unreachable", "params": {}})]
    assert held.applied_hash == ""
    assert held.state_error["code"] == "hub_unreachable"
    assert held._tried_hash == ""

    held.take(state(gitea="installed"))
    drive_once(held)
    assert len(engine.installs) == 2


def test_a_socket_that_refuses_the_stream_is_the_same_as_none(tmp_path):
    def refuse(kind, **args):
        raise GatewayUnreachable("gone")

    runners = {"gitea": FakeRunner()}
    engine = FakeEngine(runners, absent=("gitea",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path, open_stream=refuse)

    held.apply(state(gitea="installed"))

    assert engine.installs == [("gitea", {"code": "hub_unreachable", "params": {}})]
    assert held._tried_hash == ""


# --- the hash and the error ---


def test_the_hash_moves_only_when_every_mentioned_module_applied(tmp_path):
    runners = {
        "samba": FakeRunner(),
        "gitea": FakeRunner(failure=ModuleApplyError("port_reserved", {"port": 80})),
    }
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running", gitea="running"))

    assert held.applied_hash == ""
    assert held.state_error == {
        "code": "port_reserved",
        "params": {"module": "gitea", "port": 80},
    }
    assert engine.results["gitea"] == ("port_reserved", {"port": 80})
    assert engine.results["samba"] == ("", {})


def test_the_state_error_names_the_first_failure(tmp_path):
    runners = {
        "zfs": FakeRunner(failure=RuntimeError("disk on fire")),
        "podman": FakeRunner(failure=ModuleApplyError("mirror_invalid")),
    }
    held, _ = applier(runners, tmp_path=tmp_path)

    held.apply(state(zfs="running", podman="running"))

    assert held.state_error["code"] == "apply_failed"
    assert held.state_error["params"]["module"] == "zfs"
    assert "disk on fire" in held.state_error["params"]["detail"]


def test_a_success_after_a_failure_clears_the_error(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("samba_missing"))}
    held, _ = applier(runners, tmp_path=tmp_path)
    held.apply(state(samba="running"))
    assert held.state_error is not None

    runners["samba"].failure = None
    held.apply(state("h2", samba="running"))

    assert held.applied_hash == "h2"
    assert held.state_error is None


# --- taking states from the hub ---


def test_take_keeps_the_state_and_the_worker_applies_it(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners)
    held = DesiredStateApplier(
        engine=engine,
        runners=runners,
        store=DesiredStateStore(path=str(tmp_path / "desired.json")),
        log=lambda message: None,
    )

    held.take(state(samba="running"))

    deadline = 50
    while held.applied_hash != "h1" and deadline:
        threading.Event().wait(0.02)
        deadline -= 1
    assert held.applied_hash == "h1"
    assert json.loads((tmp_path / "desired.json").read_text())["hash"] == "h1"
    assert runners["samba"].applied == [{"n": "samba"}]


def test_a_state_already_applied_is_not_applied_twice(tmp_path):
    runners = {"samba": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path)
    held.apply(state(samba="running"))

    held.take(state(samba="running"))
    drive_once(held)

    assert runners["samba"].applied == [{"n": "samba"}]


def test_a_failed_state_keeps_the_old_hash_and_is_not_tried_again_under_it(
    tmp_path,
):
    """Trying again is a person's word: it arrives as a state with another
    hash, never as the same one repeated."""
    runners = {"samba": FakeRunner(failure=ModuleApplyError("samba_missing"))}
    held, _ = applier(runners, tmp_path=tmp_path)
    held.apply(state("h1", samba="running"))
    held._applied_hash = "h0"
    held.apply(state("h1", samba="running"))
    held._applied_hash = "h0"

    held.take(state("h1", samba="running"))
    drive_once(held)

    assert held.applied_hash == "h0"
    assert held.state_error["code"] == "samba_missing"
    assert len(runners["samba"].applied) == 0
    assert held._tried_hash == "h1"


def test_a_failed_install_is_not_tried_again_under_the_same_hash(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(
        runners,
        absent=("samba",),
        install_refusal={"code": "install_failed", "params": {"detail": "dpkg"}},
    )
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    held.apply(state("h1", samba="running"))

    held.take(state("h1", samba="running"))
    drive_once(held)

    assert len(engine.installs) == 1
    assert held._tried_hash == "h1"
    assert held.state_error["params"] == {"module": "samba", "detail": "dpkg"}


def test_a_state_with_another_hash_is_tried_after_a_failure(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("samba_missing"))}
    held, _ = applier(runners, tmp_path=tmp_path)
    held.apply(state("h1", samba="running"))
    runners["samba"].failure = None

    held.take(state("h2", samba="running"))
    drive_once(held)

    assert held.applied_hash == "h2"
    assert held.state_error is None
    assert runners["samba"].applied == [{"n": "samba"}]


def test_settle_returns_once_the_taken_state_has_applied(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners)
    held = DesiredStateApplier(
        engine=engine,
        runners=runners,
        store=DesiredStateStore(path=str(tmp_path / "desired.json")),
        log=lambda message: None,
    )

    held.take(state(samba="running"))

    assert held.settle(5.0)
    assert held.applied_hash == "h1"
    assert runners["samba"].applied == [{"n": "samba"}]
    assert held.settle(0.1)


# --- the desktop section of the state ---


def test_the_seat_password_reaches_the_desktop_host(tmp_path):
    host = FakeShareHost()
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    document = state(samba="running")
    document["desktop"] = {"seat_password": "hunter2"}  # scan: allow

    held.apply(document)

    assert host.passwords == ["hunter2"]


def test_a_state_with_no_desktop_section_hands_the_host_nothing(tmp_path):
    host = FakeShareHost()
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    document = state(samba="running")
    document.pop("desktop")

    held.apply(document)

    assert host.passwords == []


def test_a_password_the_host_refuses_does_not_fail_the_state(tmp_path):
    """What RustDesk did with a password says nothing about whether the
    modules applied."""
    host = FakeShareHost(refusal={"code": "rdp_password_refused", "params": {}})
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    document = state(samba="running")
    document["desktop"] = {"seat_password": "hunter2"}  # scan: allow

    held.apply(document)

    assert held.applied_hash == "h1"
    assert held.state_error is None


def test_nothing_here_forces_a_state_again():
    """An install is the reconcile's own step now; there is no second
    pass to ask for after it."""
    assert not hasattr(DesiredStateApplier, "apply_again")
    assert pytest is not None
