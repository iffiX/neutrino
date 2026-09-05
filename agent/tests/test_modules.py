"""Reconciling modules on a device, with typed statuses.

The failures the package reconciler is built around, both found on a real
box: an install whose verify never confirms must not be re-downloaded every
idle re-check, and a removal that did not take must not be re-run every
minute either — todesk's removal ran every sixty seconds all night because
``dpkg -s`` read the half-removed ``rc`` state as installed and nothing
remembered the attempt.
"""

import subprocess
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

DEB_MANIFEST = {
    "name": "todesk",
    "kind": "package",
    "platforms": {
        "debian": {
            "url": "https://example.invalid/todesk.deb",
            "package_kind": "deb",
            "uninstall": "apt-get remove -y todesk",
        }
    },
}


class RecordingPlatform(AgentPlatform):
    """Counts installs and removals instead of running them."""

    os_name = "linux"

    def __init__(self):
        self.installs: list = []
        self.removals: list = []

    def install_package(self, path, *, package_kind, entry):
        self.installs.append(1)

    def uninstall_package(self, command):
        self.removals.append(command)


def discard(message: str) -> None:
    """Swallow the log lines."""


@pytest.fixture
def reconciler(monkeypatch):
    """One reconciler whose installs are counted and whose verify never
    confirms, which is the shape of the manifest bug."""
    monkeypatch.setattr(package_module, "download", lambda *a, **k: None)
    monkeypatch.setattr(package_module, "verify_package", lambda *a, **k: None)
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest, entry: False
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)
    return subject, platform


def entry() -> dict:
    return MANIFEST["platforms"]["debian"]


def deb_entry() -> dict:
    return DEB_MANIFEST["platforms"]["debian"]


def wanted(is_enabled: bool) -> dict:
    return {"is_enabled": is_enabled}


def test_an_install_whose_verify_never_confirms_runs_once(reconciler):
    subject, platform = reconciler

    first = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )
    second = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )
    third = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    assert len(platform.installs) == 1
    assert second == first
    assert third == first
    assert first["code"] == "verify_unconfirmed"


def test_removing_it_makes_installing_worth_trying_again(reconciler):
    subject, platform = reconciler
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

    assert len(platform.installs) == 2


def test_an_install_that_does_confirm_is_not_remembered_as_unconfirmed(
    reconciler, monkeypatch
):
    subject, platform = reconciler
    answers = iter([False, True])
    monkeypatch.setattr(
        PackageModuleReconciler,
        "_verify",
        lambda self, manifest, entry: next(answers, True),
    )

    state = subject.reconcile(
        name="todesk", manifest=MANIFEST, entry=entry(), wanted=wanted(True)
    )

    assert state == {"state": "installed", "code": "", "params": {}, "is_active": False}
    assert subject._install_unconfirmed == set()


# --- the removal latch: the real box re-ran todesk's removal all night ---


def test_a_removal_that_did_not_take_runs_once_and_latches(monkeypatch):
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest, entry: True
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)

    first = subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )
    second = subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )

    assert len(platform.removals) == 1
    assert first["code"] == "remove_unconfirmed"
    assert second == first


def test_asking_to_install_again_clears_the_removal_latch(monkeypatch):
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest, entry: True
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)
    subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )

    subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(True)
    )
    subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )

    assert len(platform.removals) == 2


def test_a_removal_that_verifies_gone_clears_the_latch(monkeypatch):
    answers = iter([True, False])
    monkeypatch.setattr(
        PackageModuleReconciler,
        "_verify",
        lambda self, manifest, entry: next(answers, False),
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)

    state = subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )

    assert state["state"] == "absent"
    assert subject._remove_unconfirmed == set()


def test_a_deb_removal_purges_by_package_name(monkeypatch):
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest, entry: True
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)

    subject.reconcile(
        name="todesk", manifest=DEB_MANIFEST, entry=deb_entry(), wanted=wanted(False)
    )

    assert platform.removals == ["apt-get purge -y todesk"]


def test_a_non_deb_removal_keeps_the_manifest_command(monkeypatch):
    monkeypatch.setattr(
        PackageModuleReconciler, "_verify", lambda self, manifest, entry: True
    )
    platform = RecordingPlatform()
    subject = PackageModuleReconciler(platform=platform, log=discard)
    manifest = {
        "name": "anydesk",
        "kind": "package",
        "platforms": {
            "darwin": {
                "package_kind": "dmg",
                "uninstall": "rm -rf /Applications/AnyDesk.app",
            }
        },
    }

    subject.reconcile(
        name="anydesk",
        manifest=manifest,
        entry=manifest["platforms"]["darwin"],
        wanted=wanted(False),
    )

    assert platform.removals == ["rm -rf /Applications/AnyDesk.app"]


# --- the deb verify matrix: only "install ok installed" counts ---


def deb_verify(monkeypatch, *, returncode, stdout):
    def fake_run(command, **kwargs):
        assert command == ["dpkg-query", "-W", "-f=${Status}", "todesk"]
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    monkeypatch.setattr(package_module.subprocess, "run", fake_run)
    subject = PackageModuleReconciler(platform=RecordingPlatform(), log=discard)
    return subject._verify(DEB_MANIFEST, deb_entry())


def test_deb_verify_installed(monkeypatch):
    assert deb_verify(monkeypatch, returncode=0, stdout="install ok installed") is True


def test_deb_verify_the_rc_state_is_not_installed(monkeypatch):
    assert (
        deb_verify(monkeypatch, returncode=0, stdout="deinstall ok config-files")
        is False
    )


def test_deb_verify_absent(monkeypatch):
    assert deb_verify(monkeypatch, returncode=1, stdout="") is False


# --- the SSH server: enabled and disabled, never installed or removed ---


class SwitchPlatform(AgentPlatform):
    os_name = "linux"

    def __init__(self, *, is_running: bool):
        self.is_running = is_running
        self.calls: list = []

    def read_openssh_status(self, entry) -> bool:
        return self.is_running

    def enable_openssh(self, entry) -> None:
        self.calls.append("enable")
        self.is_running = True

    def disable_openssh(self, entry) -> None:
        self.calls.append("disable")
        self.is_running = False


def openssh_reconcile(platform, wish):
    subject = OpensshModuleReconciler(platform=platform, log=discard)
    return subject.reconcile(
        name="openssh_server",
        manifest={"kind": "openssh"},
        entry={"service": "ssh"},
        wanted=wish,
    )


def test_openssh_is_enabled_when_asked():
    platform = SwitchPlatform(is_running=False)

    state = openssh_reconcile(platform, wanted(True))

    assert platform.calls == ["enable"]
    assert state["state"] == "enabled"


def test_openssh_is_disabled_when_asked():
    platform = SwitchPlatform(is_running=True)

    state = openssh_reconcile(platform, wanted(False))

    assert platform.calls == ["disable"]
    assert state["state"] == "disabled"


def test_openssh_already_converged_is_only_reported():
    platform = SwitchPlatform(is_running=True)

    state = openssh_reconcile(platform, wanted(True))

    assert platform.calls == []
    assert state["state"] == "enabled"


def test_openssh_undecided_is_reported_never_touched():
    platform = SwitchPlatform(is_running=False)

    state = openssh_reconcile(platform, None)

    assert platform.calls == []
    assert state["state"] == "disabled"


# --- the engine's own judgments ---


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
