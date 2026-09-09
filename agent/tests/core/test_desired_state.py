"""The desired state: kept root-only, applied in one order, hashed honestly.

What these pin: the fixed module order, an installed-and-disabled module
stopped, a module not installed skipped, the applied hash moving only when
every enabled module applied, the first failure naming the state error,
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
from neutrino_agent.modules.base import ModuleApplyError

RESOLVED = {"kind": "system_package", "entry": {"packages": ["x"]}}


class FakeEngine:
    """Holds a catalog and records what the applier tells it."""

    def __init__(self, names):
        self.catalog = {name: dict(RESOLVED) for name in names}
        self.updates: list = []
        self.results: dict = {}
        self.refreshes = 0

    def update(self, *, catalog, catalog_hash):
        self.updates.append((catalog, catalog_hash))

    def resolved(self, name):
        return self.catalog.get(name)

    def record_apply(self, name, code, params):
        self.results[name] = (code, dict(params))

    def refresh_now(self):
        self.refreshes += 1


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

    def __init__(self, *, is_installed=True, failure=None, journal=None):
        self.is_installed = is_installed
        self.failure = failure
        self.journal = journal if journal is not None else []
        self.applied: list = []
        self.stops = 0

    def verify(self, resolved):
        return self.is_installed

    def apply(self, config):
        if self.failure is not None:
            raise self.failure
        self.applied.append(config)
        self.journal.append(("apply", id(self)))

    def stop(self):
        self.stops += 1
        self.journal.append(("stop", id(self)))


def desired(**modules) -> dict:
    return {
        "modules": {
            name: {"is_enabled": is_enabled, "config": {"n": name}}
            for name, is_enabled in modules.items()
        },
        "rdp": {"seat_password": ""},
        "catalog": {"modules": {name: dict(RESOLVED) for name in modules}},
    }


def applier(runners, engine=None, tmp_path=None, rdp=None):
    engine = engine if engine is not None else FakeEngine(runners)
    held = DesiredStateApplier.__new__(DesiredStateApplier)
    held._engine = engine
    held._runners = dict(runners)
    held._store = DesiredStateStore(path=str(tmp_path / "desired.json"))
    held._rdp = rdp
    held._log = lambda message: None
    held._lock = threading.Lock()
    held._idle = threading.Condition(held._lock)
    held._is_applying = False
    held._pending = None
    held._applied_hash = ""
    held._state_error = None
    held._wakeup = threading.Event()
    return held, engine


# --- the store ---


def test_the_file_is_written_root_only_and_reads_back(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "agent/desired.json"))

    store.write("h1", {"modules": {}})

    mode = stat.S_IMODE(os.stat(tmp_path / "agent/desired.json").st_mode)
    assert mode == 0o600
    assert store.read() == ("h1", {"modules": {}})


def test_a_missing_or_broken_file_reads_as_nothing(tmp_path):
    store = DesiredStateStore(path=str(tmp_path / "desired.json"))
    assert store.read() == ("", {})

    (tmp_path / "desired.json").write_text("not json")
    assert store.read() == ("", {})


# --- the order and the verbs ---


def test_modules_apply_in_the_fixed_order(tmp_path):
    journal: list = []
    runners = {name: FakeRunner(journal=journal) for name in reversed(APPLY_ORDER)}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply("h1", desired(**{name: True for name in APPLY_ORDER}))

    assert [id(runners[name]) for name in APPLY_ORDER] == [
        entry[1] for entry in journal
    ]
    assert all(entry[0] == "apply" for entry in journal)
    assert engine.updates[0][1] == "h1"
    assert engine.updates[0][0]["modules"].keys() == set(APPLY_ORDER)


def test_an_installed_disabled_module_is_stopped(tmp_path):
    runners = {"samba": FakeRunner()}
    held, _ = applier(runners, tmp_path=tmp_path)

    held.apply("h1", desired(samba=False))

    assert runners["samba"].stops == 1
    assert runners["samba"].applied == []


def test_a_module_that_is_not_installed_is_skipped(tmp_path):
    runners = {"samba": FakeRunner(is_installed=False)}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply("h1", desired(samba=True))

    assert runners["samba"].applied == []
    assert runners["samba"].stops == 0
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_the_hash_moves_only_when_every_enabled_module_applied(tmp_path):
    runners = {
        "samba": FakeRunner(),
        "gitea": FakeRunner(failure=ModuleApplyError("port_reserved", {"port": 80})),
    }
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply("h1", desired(samba=True, gitea=True))

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

    held.apply("h1", desired(zfs=True, podman=True))

    assert held.state_error["code"] == "apply_failed"
    assert held.state_error["params"]["module"] == "zfs"
    assert "disk on fire" in held.state_error["params"]["detail"]


def test_a_success_after_a_failure_clears_the_error(tmp_path):
    runners = {"samba": FakeRunner(failure=ModuleApplyError("samba_missing"))}
    held, _ = applier(runners, tmp_path=tmp_path)
    held.apply("h1", desired(samba=True))
    assert held.state_error is not None

    runners["samba"].failure = None
    held.apply("h2", desired(samba=True))

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

    held.take("h1", desired(samba=True))

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
    held.apply("h1", desired(samba=True))

    held._pending = ("h1", desired(samba=True))
    held._wakeup.set()
    # Drive the worker's own loop once, in this thread.
    with held._lock:
        pending = held._pending
        held._pending = None
    assert pending[0] == held.applied_hash
    assert runners["samba"].applied == [{"n": "samba"}]


def test_apply_again_forces_the_last_state_after_an_order(tmp_path):
    runners = {"samba": FakeRunner(is_installed=False)}
    held, _ = applier(runners, tmp_path=tmp_path)
    held._store.write("h1", desired(samba=True))
    held.apply("h1", desired(samba=True))
    assert held.applied_hash == "h1"

    runners["samba"].is_installed = True
    held.apply_again()

    assert held.applied_hash == ""
    assert held._pending[0] == "h1"
    assert held._wakeup.is_set()


def test_settle_returns_once_the_taken_state_has_applied(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners)
    held = DesiredStateApplier(
        engine=engine,
        runners=runners,
        store=DesiredStateStore(path=str(tmp_path / "desired.json")),
        log=lambda message: None,
    )

    held.take("h1", desired(samba=True))

    assert held.settle(5.0)
    assert held.applied_hash == "h1"
    assert runners["samba"].applied == [{"n": "samba"}]
    assert held.settle(0.1)


# --- the desktop half of the state ---


def test_the_seat_password_reaches_the_desktop_host(tmp_path):
    host = FakeShareHost()
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    state = desired(samba=True)
    state["rdp"] = {"seat_password": "hunter2"}  # scan: allow

    held.apply("h1", state)

    assert host.passwords == ["hunter2"]


def test_a_state_with_no_desktop_block_hands_the_host_nothing(tmp_path):
    host = FakeShareHost()
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    state = desired(samba=True)
    state.pop("rdp")

    held.apply("h1", state)

    assert host.passwords == []


def test_a_password_the_host_refuses_does_not_fail_the_state(tmp_path):
    """What RustDesk did with a password says nothing about whether the
    modules applied."""
    host = FakeShareHost(refusal={"code": "rdp_password_refused", "params": {}})
    held, _engine = applier({"samba": FakeRunner()}, tmp_path=tmp_path, rdp=host)
    state = desired(samba=True)
    state["rdp"] = {"seat_password": "hunter2"}  # scan: allow

    held.apply("h1", state)

    assert held.applied_hash == "h1"
    assert held.state_error is None
