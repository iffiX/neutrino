"""Reconciling a downloaded-package module, with typed statuses.

The failures the package reconciler is built around, both found on a real
box: an install whose verify never confirms must not be re-downloaded every
idle re-check, and a removal that did not take must not be re-run every
minute either — todesk's removal ran every sixty seconds all night because
``dpkg -s`` read the half-removed ``rc`` state as installed and nothing
remembered the attempt.
"""

import os
import subprocess

import pytest

from neutrino_agent.modules import package as package_module
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules.package import PackageModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from tests.conftest import discard

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

# A kind dpkg knows nothing about: verify is the manifest's own command and
# removal is the manifest's own line.
COMMAND_MANIFEST = {
    "name": "anydesk",
    "kind": "package",
    "verify": {"linux": "which anydesk"},
    "platforms": {
        "linux": {
            "url": "https://example.invalid/anydesk.dmg",
            "package_kind": "dmg",
            "app_name": "AnyDesk.app",
            "uninstall": "rm -rf /Applications/AnyDesk.app",
        }
    },
}

PACKAGE_STEADY_STATES = {"absent", "installed"}
PACKAGE_TRANSIENT_STATES = {"installing", "removing"}
CAPABILITY_STATES = {"enabled", "disabled", "enabling", "disabling"}


def deb_entry() -> dict:
    return DEB_MANIFEST["platforms"]["debian"]


def command_entry() -> dict:
    return COMMAND_MANIFEST["platforms"]["linux"]


class RecordingPlatform(AgentPlatform):
    """Records installs and removals instead of running them."""

    os_name = "linux"

    def __init__(self, *, install_error=None, remove_error=None):
        self.installs: list = []
        self.removals: list = []
        self._install_error = install_error
        self._remove_error = remove_error

    def install_package(self, path, *, package_kind, entry):
        self.installs.append((os.path.basename(path), package_kind, entry))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.removals.append(command)
        if self._remove_error is not None:
            raise self._remove_error


class RecordingDownloads:
    """What the reconciler fetched and checked, instead of a network."""

    def __init__(self):
        self.fetched: list = []
        self.checked: list = []

    def download(self, url, path, *, is_impersonated=False):
        self.fetched.append((url, os.path.basename(path), is_impersonated))

    def verify(self, path, package_kind):
        self.checked.append((os.path.basename(path), package_kind))


class PackageHarness:
    """One reconciler and every fake it drives."""

    def __init__(self, *, reconciler, platform, downloads, published):
        self.reconciler = reconciler
        self.platform = platform
        self.downloads = downloads
        self.published = published

    def reconcile(self, wish, *, manifest=DEB_MANIFEST, entry=None):
        """One reconcile pass.

        Args:
            wish: True to install, False to remove, None to only report.
            manifest: The manifest to reconcile.
            entry: Its platform entry; the manifest's own by default.

        Returns:
            The typed status.
        """
        if entry is None:
            entry = manifest["platforms"][next(iter(manifest["platforms"]))]
        return self.reconciler.reconcile(
            name=manifest["name"],
            manifest=manifest,
            entry=entry,
            wanted=None if wish is None else {"is_enabled": wish},
        )


def _verify_answers(*answers):
    """A ``_verify`` answering from a sequence, the last answer repeating."""
    remaining = list(answers)

    def _verify(self, manifest, entry) -> bool:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return _verify


@pytest.fixture
def harness(monkeypatch):
    """Builds package reconcilers whose downloads and verify are faked."""

    def build(*answers, install_error=None, remove_error=None) -> PackageHarness:
        downloads = RecordingDownloads()
        published: list = []
        monkeypatch.setattr(package_module, "download", downloads.download)
        monkeypatch.setattr(package_module, "verify_package", downloads.verify)
        monkeypatch.setattr(
            PackageModuleReconciler, "_verify", _verify_answers(*answers)
        )
        platform = RecordingPlatform(
            install_error=install_error, remove_error=remove_error
        )
        return PackageHarness(
            reconciler=PackageModuleReconciler(
                platform=platform,
                log=discard,
                publish=lambda name, status: published.append((name, status["state"])),
            ),
            platform=platform,
            downloads=downloads,
            published=published,
        )

    return build


# --- what the hub never asked about, and what is already converged ---


@pytest.mark.parametrize(
    "is_installed, state", [(True, "installed"), (False, "absent")]
)
def test_package_never_asked_is_reported_untouched(harness, is_installed, state):
    package = harness(is_installed)

    status = package.reconcile(None)

    assert status == {"state": state, "code": "", "params": {}, "is_active": False}
    assert (package.platform.installs, package.platform.removals) == ([], [])
    assert package.published == []


@pytest.mark.parametrize("wish, state", [(True, "installed"), (False, "absent")])
def test_package_already_converged_is_reported_untouched(harness, wish, state):
    package = harness(wish)

    status = package.reconcile(wish)

    assert status == {"state": state, "code": "", "params": {}, "is_active": False}
    assert (package.platform.installs, package.platform.removals) == ([], [])
    assert package.published == []


# --- the install path ---


def test_package_wanted_and_absent_is_downloaded_checked_and_installed(harness):
    package = harness(False, True)

    status = package.reconcile(True)

    assert status == {
        "state": "installed",
        "code": "",
        "params": {},
        "is_active": False,
    }
    assert package.downloads.fetched == [
        ("https://example.invalid/todesk.deb", "package.deb", False)
    ]
    assert package.downloads.checked == [("package.deb", "deb")]
    assert package.platform.installs == [("package.deb", "deb", deb_entry())]


def test_package_install_publishes_installing_before_the_result(harness):
    package = harness(False, True)

    package.reconcile(True)

    assert package.published == [("todesk", "installing")]


def test_package_install_impersonates_where_the_manifest_asks(harness):
    package = harness(False, True)
    manifest = dict(DEB_MANIFEST, download={"impersonate": True})

    package.reconcile(True, manifest=manifest)

    assert package.downloads.fetched[0][2] is True


def test_package_install_resolves_a_github_asset_when_no_url_is_named(
    harness, monkeypatch
):
    resolved: list = []

    def resolve(repo, pattern):
        resolved.append((repo, pattern))
        return "https://example.invalid/asset.deb"

    monkeypatch.setattr(package_module, "resolve_github_asset", resolve)
    package = harness(False, True)
    entry = {"github_repo": "vendor/app", "asset_pattern": "*.deb"}

    status = package.reconcile(True, entry=entry)

    assert resolved == [("vendor/app", "*.deb")]
    assert package.downloads.fetched[0][0] == "https://example.invalid/asset.deb"
    assert status["state"] == "installed"


def test_package_install_with_no_download_named_is_failed_untouched(harness):
    package = harness(False)

    status = package.reconcile(True, entry={})

    assert status == {
        "state": "failed",
        "code": "no_download_named",
        "params": {},
        "is_active": False,
    }
    assert (package.downloads.fetched, package.platform.installs) == ([], [])


def test_package_install_that_refuses_is_left_to_the_engine_to_type(harness):
    package = harness(False, install_error=InstallError("dpkg failed: held broken"))

    with pytest.raises(InstallError):
        package.reconcile(True)

    assert len(package.platform.installs) == 1


def test_package_install_on_a_platform_that_installs_nothing_is_not_swallowed(harness):
    package = harness(
        False, install_error=PlatformUnsupportedError("cannot install packages here")
    )

    with pytest.raises(PlatformUnsupportedError):
        package.reconcile(True)

    assert len(package.platform.installs) == 1


# --- the removal path ---


def test_package_unwanted_and_installed_is_removed(harness):
    package = harness(True, False)

    status = package.reconcile(False)

    assert status == {"state": "absent", "code": "", "params": {}, "is_active": False}
    assert package.platform.removals == ["apt-get purge -y todesk"]


def test_package_removal_publishes_removing_before_the_result(harness):
    package = harness(True, False)

    package.reconcile(False)

    assert package.published == [("todesk", "removing")]


def test_package_deb_removal_purges_the_entry_package_name(harness):
    package = harness(True, False)
    entry = dict(deb_entry(), package="todesk-lite")

    package.reconcile(False, entry=entry)

    assert package.platform.removals == ["apt-get purge -y todesk-lite"]


def test_package_non_deb_removal_keeps_the_manifest_command(harness):
    package = harness(True, False)

    package.reconcile(False, manifest=COMMAND_MANIFEST)

    assert package.platform.removals == ["rm -rf /Applications/AnyDesk.app"]


def test_package_removal_with_no_command_named_stays_installed_untouched(harness):
    package = harness(True)
    entry = {"package_kind": "dmg"}

    status = package.reconcile(False, manifest=COMMAND_MANIFEST, entry=entry)

    assert status == {
        "state": "installed",
        "code": "",
        "params": {},
        "is_active": False,
    }
    assert (package.platform.removals, package.published) == ([], [])


def test_package_removal_that_refuses_is_left_to_the_engine_to_type(harness):
    package = harness(True, remove_error=InstallError("removal failed: in use"))

    with pytest.raises(InstallError):
        package.reconcile(False)

    assert package.platform.removals == ["apt-get purge -y todesk"]


# --- the install latch: an install whose verify never confirms ---


def test_package_install_unconfirmed_runs_once(harness):
    package = harness(False)

    first = package.reconcile(True)
    second = package.reconcile(True)
    third = package.reconcile(True)

    assert len(package.platform.installs) == 1
    assert first == {
        "state": "installed",
        "code": "verify_unconfirmed",
        "params": {},
        "is_active": False,
    }
    assert (second, third) == (first, first)
    assert len(package.downloads.fetched) == 1


def test_package_install_unconfirmed_survives_a_report_only_recheck(harness):
    package = harness(False)
    package.reconcile(True)

    package.reconcile(None)
    status = package.reconcile(True)

    assert len(package.platform.installs) == 1
    assert status["code"] == "verify_unconfirmed"


def test_package_install_unconfirmed_is_cleared_by_a_removal(harness):
    package = harness(False)
    package.reconcile(True)

    package.reconcile(False)
    package.reconcile(True)

    assert len(package.platform.installs) == 2


def test_package_install_confirmed_leaves_no_latch(harness):
    package = harness(False, True)

    status = package.reconcile(True)

    assert status == {
        "state": "installed",
        "code": "",
        "params": {},
        "is_active": False,
    }
    assert package.reconciler._install_unconfirmed == set()


# --- the removal latch: the real box re-ran todesk's removal all night ---


def test_package_removal_unconfirmed_runs_once(harness):
    package = harness(True)

    first = package.reconcile(False)
    second = package.reconcile(False)
    third = package.reconcile(False)

    assert len(package.platform.removals) == 1
    assert first == {
        "state": "installed",
        "code": "remove_unconfirmed",
        "params": {},
        "is_active": False,
    }
    assert (second, third) == (first, first)


def test_package_removal_unconfirmed_survives_a_report_only_recheck(harness):
    package = harness(True)
    package.reconcile(False)

    package.reconcile(None)
    status = package.reconcile(False)

    assert len(package.platform.removals) == 1
    assert status["code"] == "remove_unconfirmed"


def test_package_removal_unconfirmed_is_cleared_by_an_install(harness):
    package = harness(True)
    package.reconcile(False)

    package.reconcile(True)
    package.reconcile(False)

    assert len(package.platform.removals) == 2


def test_package_removal_confirmed_leaves_no_latch(harness):
    package = harness(True, False)

    status = package.reconcile(False)

    assert status["state"] == "absent"
    assert package.reconciler._remove_unconfirmed == set()


# --- verify is dpkg's own status word ---


def deb_verify(monkeypatch, *, returncode=0, stdout="", error=None, package="todesk"):
    commands: list = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    monkeypatch.setattr(package_module.subprocess, "run", fake_run)
    subject = PackageModuleReconciler(platform=RecordingPlatform(), log=discard)
    manifest = dict(DEB_MANIFEST, name=package)
    is_installed = subject._verify(manifest, deb_entry())
    return is_installed, commands


@pytest.mark.parametrize(
    "stdout, is_installed",
    [
        ("install ok installed", True),
        ("install ok installed\n", True),
        # The half-removed rc state a plain remove leaves behind.
        ("deinstall ok config-files", False),
        ("install ok half-configured", False),
        ("unknown ok not-installed", False),
    ],
)
def test_package_deb_verify_reads_the_status_word(monkeypatch, stdout, is_installed):
    result, commands = deb_verify(monkeypatch, stdout=stdout)

    assert result is is_installed
    assert commands == [["dpkg-query", "-W", "-f=${Status}", "todesk"]]


def test_package_deb_verify_an_unknown_package_is_absent(monkeypatch):
    result, commands = deb_verify(monkeypatch, returncode=1, stdout="")

    assert result is False
    assert commands == [["dpkg-query", "-W", "-f=${Status}", "todesk"]]


@pytest.mark.parametrize(
    "error", [OSError("no dpkg-query"), subprocess.TimeoutExpired("dpkg-query", 30)]
)
def test_package_deb_verify_a_query_that_cannot_run_is_absent(monkeypatch, error):
    result, _ = deb_verify(monkeypatch, error=error)

    assert result is False


def test_package_deb_verify_without_a_package_name_asks_dpkg_nothing(monkeypatch):
    result, commands = deb_verify(
        monkeypatch, stdout="install ok installed", package=""
    )

    assert (result, commands) == (False, [])


# --- verify for every other kind is the manifest's own command ---


def command_verify(monkeypatch, *, returncode=0, error=None, manifest=COMMAND_MANIFEST):
    calls: list = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("shell"), kwargs.get("timeout")))
        if error is not None:
            raise error
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(package_module.subprocess, "run", fake_run)
    subject = PackageModuleReconciler(platform=RecordingPlatform(), log=discard)
    return subject._verify(manifest, command_entry()), calls


def test_package_command_verify_zero_exit_is_installed(monkeypatch):
    result, calls = command_verify(monkeypatch)

    assert result is True
    assert calls == [("which anydesk", True, package_module.VERIFY_TIMEOUT_S)]


def test_package_command_verify_non_zero_exit_is_absent(monkeypatch):
    result, calls = command_verify(monkeypatch, returncode=1)

    assert (result, len(calls)) == (False, 1)


def test_package_command_verify_with_no_command_for_this_os_is_absent(monkeypatch):
    manifest = dict(COMMAND_MANIFEST, verify={"darwin": "test -d /Applications"})

    result, calls = command_verify(monkeypatch, manifest=manifest)

    assert (result, calls) == (False, [])


@pytest.mark.parametrize(
    "error", [OSError("no shell"), subprocess.TimeoutExpired("which", 30)]
)
def test_package_command_verify_that_cannot_run_is_absent(monkeypatch, error):
    result, calls = command_verify(monkeypatch, error=error)

    assert (result, len(calls)) == (False, 1)


# --- the words this reconciler may say ---


def test_package_states_are_the_package_half_of_the_table(harness):
    package = harness(False, False, True, True, False)

    reported = {
        package.reconcile(None)["state"],
        package.reconcile(True)["state"],
        package.reconcile(False)["state"],
    }

    assert reported == PACKAGE_STEADY_STATES
    assert [state for _, state in package.published] == ["installing", "removing"]
    assert not (reported | PACKAGE_TRANSIENT_STATES) & CAPABILITY_STATES
