"""The hub's state: kept root-only, applied in one order, hashed honestly.

What these pin: the fixed module order, what each ``want`` does to a
module that is there (running configures and leaves the unit up, stopped
configures and stops it, installed and absent leave the configuration
alone), a module the state does not mention untouched, a module whose
software is absent left for its install, the applied hash moving only when
every mentioned module applied, a failed state reported under the old hash
and tried again only under another hash, the first failure naming the
state error, the file's mode, and the latest state winning when several
arrive.
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
from neutrino_agent.exceptions import ModuleApplyError

INSTALL = {"kind": "system_package", "packages": ["x"], "verify": ""}


class FakeEngine:
    """Observes a scripted set of installed modules and records the rest."""

    def __init__(self, names, *, absent=()):
        self.installed = {name for name in names if name not in absent}
        self.states: list = []
        self.results: dict = {}
        self.refreshes = 0

    def take_state(self, modules):
        self.states.append(modules)

    def is_installed(self, name):
        return name in self.installed

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


def state(state_hash: str = "h1", **wants) -> dict:
    """One state document naming each module with its want."""
    return {
        "hash": state_hash,
        "modules": {
            name: {
                "want": want,
                "config": {"n": name},
                "install": dict(INSTALL),
                "uninstall": {},
            }
            for name, want in wants.items()
        },
        "desktop": {"seat_password": ""},
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


# --- the order and the wants ---


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


def test_running_configures_and_leaves_the_unit_up(tmp_path):
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert runners["samba"].applied == [{"n": "samba"}]
    assert runners["samba"].stops == 0
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


def test_stopped_configures_then_stops_the_unit(tmp_path):
    journal: list = []
    runners = {"samba": FakeRunner(journal=journal)}
    held, _ = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="stopped"))

    assert runners["samba"].applied == [{"n": "samba"}]
    assert [entry[0] for entry in journal] == ["apply", "stop"]
    assert held.applied_hash == "h1"


@pytest.mark.parametrize("want", ["installed", "absent"])
def test_installed_and_absent_leave_the_configuration_alone(tmp_path, want):
    """Both are recorded as what is wanted and reported against what is
    observed; the install and the uninstall are the reconcile's own."""
    runners = {"samba": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba=want))

    assert runners["samba"].applied == []
    assert runners["samba"].stops == 0
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})
    assert engine.states[0]["samba"]["want"] == want


def test_a_module_the_state_does_not_mention_is_untouched(tmp_path):
    runners = {"samba": FakeRunner(), "gitea": FakeRunner()}
    held, engine = applier(runners, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert runners["gitea"].applied == []
    assert runners["gitea"].stops == 0
    assert "gitea" not in engine.results
    assert held.applied_hash == "h1"


def test_a_module_whose_software_is_absent_is_left_for_its_install(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)

    held.apply(state(samba="running"))

    assert runners["samba"].applied == []
    assert runners["samba"].stops == 0
    assert held.applied_hash == "h1"
    assert engine.results["samba"] == ("", {})


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
                "uninstall": {},
            }
        }
    ]
    assert engine.refreshes == 1


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


def test_apply_again_forces_the_last_state_after_an_order(tmp_path):
    runners = {"samba": FakeRunner()}
    engine = FakeEngine(runners, absent=("samba",))
    held, _ = applier(runners, engine=engine, tmp_path=tmp_path)
    held._store.write(state(samba="running"))
    held.apply(state(samba="running"))
    assert held.applied_hash == "h1"

    engine.installed.add("samba")
    held.apply_again()

    assert held.applied_hash == ""
    assert held._tried_hash == ""
    assert held._pending["hash"] == "h1"
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
