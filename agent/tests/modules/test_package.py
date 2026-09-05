"""Reconciling modules on a device, with typed statuses.

The failures the package reconciler is built around, both found on a real
box: an install whose verify never confirms must not be re-downloaded every
idle re-check, and a removal that did not take must not be re-run every
minute either — todesk's removal ran every sixty seconds all night because
``dpkg -s`` read the half-removed ``rc`` state as installed and nothing
remembered the attempt.
"""

import subprocess

import pytest

from neutrino_agent.modules import package as package_module
from neutrino_agent.modules.package import PackageModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform
from tests.conftest import discard

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
