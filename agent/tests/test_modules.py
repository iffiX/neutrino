"""Reconciling modules on a device, with typed statuses.

The failure the package reconciler is built around: a manifest whose verify
command names the wrong path leaves a package installed and unconfirmed, and
the idle re-check a minute later reads it as absent and installs it again.
Nothing stops that loop on its own — the download is fifty megabytes and the
device repeats it every minute until somebody looks at the traffic.
"""

import threading

import pytest

from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.modules import package as package_module
from neutrino_agent.modules.openssh import OpensshModuleReconciler
from neutrino_agent.modules.package import PackageModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform

MANIFEST = {
    "name": "todesk",
    "kind": "package",
    "verify": {"linux": "false"},
    "platforms": {"debian": {"url": "https://example.invalid/todesk.deb"}},
}


class RecordingPlatform(AgentPlatform):
    """Counts installs and removals instead of running them."""

    os_name = "linux"

    def __init__(self):
        self.installs: list = []

    def install_package(self, path, *, package_kind, entry):
        self.installs.append(1)

    def uninstall_package(self, command):
        return None


def discard(message: str) -> None:
    """Swallow the log lines."""


@pytest.fixture
def reconciler(monkeypatch):
    """One reconciler whose installs are counted and whose verify never
    confirms, which is the shape of the manifest bug."""
    monkeypatch.setattr(package_module, "download", lambda *a, **k: None)
    monkeypatch.setattr(package_module, "verify_package", lambda *a, **k: None)
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest: False
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)
    return subject, platform.installs


def entry() -> dict:
    return MANIFEST["platforms"]["debian"]


def wanted(is_enabled: bool) -> dict:
    return {"is_enabled": is_enabled}


def test_an_install_whose_verify_never_confirms_runs_once(reconciler):
    subject, installs = reconciler

    first = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )
    second = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )
    third = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    assert len(installs) == 1
    assert second == first
    assert third == first
    assert first["code"] == "verify_unconfirmed"


def test_removing_it_makes_installing_worth_trying_again(reconciler):
    subject, installs = reconciler
    subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    subject.reconcile(
        name="todesk",
        manifest=MANIFEST,
        entry=dict(entry(), uninstall="apt-get remove -y todesk"),
        wanted=wanted(False),
    )
    subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    assert len(installs) == 2


def test_an_install_that_does_confirm_is_not_remembered_as_unconfirmed(
    reconciler, monkeypatch
):
    subject, installs = reconciler
    answers = iter([False, True])
    monkeypatch.setattr(
        PackageModuleReconciler,
        "_verify",
        lambda self, manifest: next(answers, True),
    )

    state = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    assert state == {"state": "installed", "code": "", "params": {}, "is_active": False}
    assert subject._unconfirmed == set()


def bare_engine() -> ModuleEngine:
    """An engine with no worker thread, for driving one reconcile directly."""
    engine = ModuleEngine.__new__(ModuleEngine)
    engine._log = discard
    engine._on_change = None
    engine._lock = threading.Lock()
    engine._statuses = {}
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._reconcilers = {
        "openssh": OpensshModuleReconciler(platform=AgentPlatform(), log=discard)
    }
    return engine


def test_an_absent_capability_reports_unsupported_platform():
    engine = bare_engine()

    status = engine._reconcile_one(
        "openssh", {"kind": "openssh", "platforms": {"linux": {}}}, None
    )

    assert status == {
        "state": "failed",
        "code": "unsupported_platform",
        "params": {},
        "is_active": False,
    }


def test_a_kind_the_engine_does_not_run_is_reported_as_unknown():
    engine = bare_engine()

    status = engine._reconcile_one(
        "ai_tools", {"kind": "ai_tools", "platforms": {"linux": {}}}, None
    )

    assert status == {
        "state": "unknown",
        "code": "unknown_kind",
        "params": {"kind": "ai_tools"},
        "is_active": False,
    }


def test_a_manifest_with_no_build_here_is_reported_not_failed():
    engine = bare_engine()

    status = engine._reconcile_one(
        "todesk", {"kind": "package", "platforms": {"windows-amd64": {}}}, None
    )

    assert status == {
        "state": "unsupported",
        "code": "no_platform_build",
        "params": {},
        "is_active": False,
    }
