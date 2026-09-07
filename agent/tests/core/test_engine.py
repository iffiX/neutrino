"""The module engine: carrying out orders, and holding no policy.

The engine is handed a catalog the hub already resolved and orders the hub
already decided on. What is pinned here is that it runs what it is given,
judges the result by the machine's own state, reports the output of a
failure — and that nothing in it ever retries anything.
"""

import pytest

from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError

DEB_ENTRY = {"package_kind": "deb", "uninstall": "apt-get remove -y fakedesk"}

CATALOG = {
    "modules": {
        "fakedesk": {
            "title": "FakeDesk",
            "kind": "package",
            "entry": DEB_ENTRY,
            "verify": "",
            "package": "fakedesk",
        }
    },
    "services": [],
}


class FakePlatform(AgentPlatform):
    """A platform that records installs and refuses nothing else."""

    os_name = "linux"

    def __init__(self, *, install_error=None):
        self.installs: list = []
        self.uninstalls: list = []
        self._install_error = install_error

    def install_package(self, path, *, package_kind, entry):
        self.installs.append((package_kind, entry))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.uninstalls.append(command)


def bare_engine(*, platform=None, fetch_artifact=None, verified=None):
    """An engine with no worker thread, driven a pass at a time.

    Args:
        platform: The machine's platform.
        fetch_artifact: What the hub hands down.
        verified: Scripted answers for verify; the last one repeats.

    Returns:
        The engine, its fetches and its verify calls.
    """
    engine = ModuleEngine.__new__(ModuleEngine)
    engine._catalog = dict(CATALOG)
    engine._catalog_hash = "abc"
    engine._platform_tuple = {"os": "linux", "family": "debian", "arch": "amd64"}
    engine._queued = []
    engine._ran = set()
    engine._results = {}
    engine._output = []
    engine._statuses = {}
    engine._signature = ""
    engine._checked_at = 0.0
    engine._log = lambda message: None
    engine._on_change = None
    import threading

    engine._lock = threading.Lock()
    engine._wakeup = threading.Event()

    from neutrino_agent.modules.openssh import OpensshModuleRunner
    from neutrino_agent.modules.package import PackageModuleRunner
    from neutrino_agent.modules.rustdesk import RustdeskModuleRunner
    from neutrino_agent.modules.switcher import SwitcherModuleRunner
    from neutrino_agent.modules.system_package import SystemPackageModuleRunner

    platform = platform if platform is not None else FakePlatform()
    engine._fetch_artifact = fetch_artifact
    engine._package = PackageModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._switcher = SwitcherModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._system = SystemPackageModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._openssh = OpensshModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._rustdesk = RustdeskModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    answers = list(verified or [])

    def verify(resolved):
        return (
            answers.pop(0) if len(answers) > 1 else (answers[0] if answers else False)
        )

    engine._package.verify = verify
    return engine


def landing_fetch(fetches):
    """A fetch that writes a package and records the key it was asked for."""

    def fetch(artifact_key, destination):
        fetches.append(artifact_key)
        with open(destination, "wb") as stream:
            stream.write(b"!<arch>package")
        return {}

    return fetch


def test_an_order_installs_what_it_is_given_and_reports_done():
    fetches: list = []
    platform = FakePlatform()
    engine = bare_engine(
        platform=platform, fetch_artifact=landing_fetch(fetches), verified=[True]
    )

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "fakedesk-linux-debian-amd64-aaaa",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    assert fetches == ["fakedesk-linux-debian-amd64-aaaa"]
    assert platform.installs == [("deb", DEB_ENTRY)]
    result = engine.results()[0]
    assert result["id"] == "order-1"
    assert result["state"] == "done"
    # Success carries its output too: a result rides once, so the log of
    # something that worked costs one message and is what a person
    # watching an install came to read.
    assert "fakedesk: installing" in result["output"]


def test_an_install_the_machine_cannot_confirm_is_failed_not_latched():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    result = engine.results()[0]
    assert result["state"] == "failed"
    assert result["code"] == "install_unconfirmed"


def test_a_failed_install_reports_the_output_it_produced():
    platform = FakePlatform(install_error=InstallError("dpkg failed: held broken"))
    engine = bare_engine(
        platform=platform, fetch_artifact=landing_fetch([]), verified=[False]
    )

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    result = engine.results()[0]
    assert result["state"] == "failed"
    assert result["code"] == "install_failed"
    # The vendor's own words, not only that something went wrong.
    assert "dpkg failed: held broken" in result["output"]


def test_a_refused_fetch_is_reported_with_the_hubs_own_code():
    def refuse(artifact_key, destination):
        return {"code": "module_fetch_failed", "params": {"detail": "refused"}}

    engine = bare_engine(fetch_artifact=refuse, verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    result = engine.results()[0]
    assert result["code"] == "module_fetch_failed"
    assert result["params"] == {"detail": "refused"}


def test_an_uninstall_is_run_and_confirmed():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "fakedesk", "action": "uninstall"}],
    )
    engine._reconcile()

    assert platform.uninstalls == ["apt-get purge -y fakedesk"]
    assert engine.results()[0]["state"] == "done"


def test_an_uninstall_that_did_not_take_is_reported_failed():
    engine = bare_engine(verified=[True])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "fakedesk", "action": "uninstall"}],
    )
    engine._reconcile()

    assert engine.results()[0]["code"] == "uninstall_unconfirmed"


def test_no_tick_ever_reruns_a_failed_order():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches), verified=[False])
    order = {
        "id": "order-1",
        "module": "fakedesk",
        "action": "install",
        "artifact_key": "key",
        "package_kind": "deb",
    }

    engine.update(catalog=None, catalog_hash="abc", orders=[order])
    engine._reconcile()
    # The hub keeps handing the same order down until it hears the result;
    # every one of those beats, and every idle pass, must run nothing.
    for _ in range(5):
        engine.update(catalog=None, catalog_hash="abc", orders=[order])
        engine._reconcile()

    assert fetches == ["key"]
    assert engine.results()[0]["code"] == "install_unconfirmed"


def test_asking_again_is_a_new_order_and_runs():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches), verified=[False])
    first = {
        "id": "order-1",
        "module": "fakedesk",
        "action": "install",
        "artifact_key": "key",
        "package_kind": "deb",
    }

    engine.update(catalog=None, catalog_hash="abc", orders=[first])
    engine._reconcile()
    # A person pressing the button again: a different id, so it runs.
    engine.update(catalog=None, catalog_hash="abc", orders=[dict(first, id="order-2")])
    engine._reconcile()

    assert fetches == ["key", "key"]


def test_a_result_the_hub_has_stopped_asking_about_is_dropped():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[True])
    order = {
        "id": "order-1",
        "module": "fakedesk",
        "action": "install",
        "artifact_key": "key",
        "package_kind": "deb",
    }

    engine.update(catalog=None, catalog_hash="abc", orders=[order])
    engine._reconcile()
    assert len(engine.results()) == 1
    # The hub no longer names it, so it has the result and this can forget.
    engine.update(catalog=None, catalog_hash="abc", orders=[])

    assert engine.results() == []


def test_an_order_for_a_module_with_no_build_here_is_refused_not_attempted():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches))
    engine._catalog = {"modules": {"fakedesk": {"kind": "package", "entry": None}}}

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
            }
        ],
    )
    engine._reconcile()

    assert fetches == []
    assert engine.results()[0]["code"] == "no_platform_build"


def test_an_action_this_agent_does_not_know_is_typed_not_guessed():
    engine = bare_engine(verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "fakedesk", "action": "reticulate"}],
    )
    engine._reconcile()

    result = engine.results()[0]
    assert result["code"] == "unknown_action"
    assert result["params"] == {"action": "reticulate"}


def test_a_platform_that_installs_nothing_is_reported_not_raised():
    engine = bare_engine(
        platform=AgentPlatform(), fetch_artifact=landing_fetch([]), verified=[False]
    )

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    assert engine.results()[0]["code"] == "unsupported_platform"


def test_reporting_a_module_touches_nothing():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[True])

    engine._refresh(is_forced=True)

    assert platform.installs == []
    assert platform.uninstalls == []
    assert engine.report()["fakedesk"]["state"] == "installed"


def test_a_module_with_no_build_here_is_reported_unsupported_not_failed():
    engine = bare_engine()
    engine._catalog = {"modules": {"fakedesk": {"kind": "package", "entry": None}}}

    engine._refresh(is_forced=True)

    assert engine.report()["fakedesk"] == {
        "state": "unsupported",
        "code": "no_platform_build",
        "params": {},
        "details": {},
    }


def test_a_kind_the_engine_does_not_run_is_reported_as_unsupported():
    """An older agent meeting a module kind a newer hub serves is a machine
    that cannot have it, not one that has not answered."""
    engine = bare_engine()
    engine._catalog = {"modules": {"thing": {"kind": "ai_tools", "entry": {}}}}

    engine._refresh(is_forced=True)

    assert engine.report()["thing"] == {
        "state": "unsupported",
        "code": "unknown_kind",
        "params": {"kind": "ai_tools"},
        "details": {},
    }


def test_an_absent_capability_reports_unsupported_platform():
    engine = bare_engine(platform=AgentPlatform())
    engine._catalog = {"modules": {"ssh_server": {"kind": "openssh", "entry": {}}}}

    engine._refresh(is_forced=True)

    assert engine.report()["ssh_server"] == {
        "state": "failed",
        "code": "unsupported_platform",
        "params": {},
        "details": {},
    }


def test_the_engine_holds_no_failure_memory():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "fakedesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    # Results are what the hub has not collected yet, not a record of what
    # failed: there is no latch, no failure map and no attempt count here.
    assert not hasattr(engine, "_install_failed")
    assert not hasattr(engine, "_install_unconfirmed")
    assert not hasattr(engine, "_remove_unconfirmed")


# --- the by-name kinds ride the same order path ---

SSH_CATALOG = {
    "modules": {
        "ssh_server": {
            "title": "SSH server",
            "kind": "openssh",
            "entry": {"packages": ["openssh-server"], "service": "ssh"},
            "verify": "",
            "package": "ssh_server",
        }
    },
    "services": [],
}


class SwitchingPlatform(AgentPlatform):
    """A platform whose SSH server can be switched and observed."""

    os_name = "linux"

    def __init__(self, *, is_running=False):
        self.is_running = is_running
        self.switches: list = []

    def read_openssh_status(self, entry):
        return self.is_running

    def install_openssh(self, entry):
        self.switches.append("install")
        self.is_running = True

    def uninstall_openssh(self, entry):
        self.switches.append("uninstall")
        self.is_running = False


def test_an_openssh_install_order_fetches_nothing_and_reports_done():
    platform = SwitchingPlatform(is_running=False)
    fetches: list = []
    engine = bare_engine(platform=platform, fetch_artifact=landing_fetch(fetches))
    engine._catalog = dict(SSH_CATALOG)

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "ssh_server", "action": "install"}],
    )
    engine._reconcile()

    assert platform.switches == ["install"]
    assert fetches == []
    result = engine.results()[0]
    assert result["state"] == "done" and result["code"] == ""
    # Every order carries its output, success included.
    assert "ssh_server: install" in result["output"]
    assert engine.report()["ssh_server"]["state"] == "installed"


def test_an_openssh_uninstall_order_takes_the_server_out_with_output():
    platform = SwitchingPlatform(is_running=True)
    engine = bare_engine(platform=platform)
    engine._catalog = dict(SSH_CATALOG)

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "ssh_server", "action": "uninstall"}],
    )
    engine._reconcile()

    assert platform.switches == ["uninstall"]
    result = engine.results()[0]
    assert result["state"] == "done" and result["code"] == ""
    assert "ssh_server: uninstall" in result["output"]
    assert engine.report()["ssh_server"]["state"] == "absent"


SYSTEM_CATALOG = {
    "modules": {
        "samba_mount": {
            "title": "Samba mount",
            "kind": "system_package",
            "entry": {"packages": ["cifs-utils"]},
            "verify": "",
            "package": "samba_mount",
        }
    },
    "services": [],
}


class SystemPackagePlatform(AgentPlatform):
    """A platform whose own package manager is observable."""

    os_name = "linux"

    def __init__(self):
        self.installed: list = []
        self.removed: list = []

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return "Setting up cifs-utils"

    def remove_system_packages(self, names):
        self.removed.append(list(names))
        return ""


def test_a_system_package_order_installs_by_name_and_fetches_nothing():
    platform = SystemPackagePlatform()
    fetches: list = []
    engine = bare_engine(platform=platform, fetch_artifact=landing_fetch(fetches))
    engine._catalog = dict(SYSTEM_CATALOG)
    engine._system.verify = lambda resolved: True

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "samba_mount", "action": "install"}],
    )
    engine._reconcile()

    assert platform.installed == [["cifs-utils"]]
    assert fetches == []
    result = engine.results()[0]
    assert result["state"] == "done"
    assert "Setting up cifs-utils" in result["output"]


def test_a_system_package_uninstall_rides_the_package_manager_too():
    platform = SystemPackagePlatform()
    engine = bare_engine(platform=platform)
    engine._catalog = dict(SYSTEM_CATALOG)
    engine._system.verify = lambda resolved: False

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "samba_mount", "action": "uninstall"}],
    )
    engine._reconcile()

    assert platform.removed == [["cifs-utils"]]
    assert engine.results()[0]["state"] == "done"


def test_a_native_system_package_reads_installed_with_nothing_to_run():
    engine = bare_engine(platform=SystemPackagePlatform())
    engine._catalog = {
        "modules": {
            "samba_mount": {
                "title": "Samba mount",
                "kind": "system_package",
                "entry": {},
                "verify": "",
                "package": "samba_mount",
            }
        },
        "services": [],
    }

    engine._refresh(is_forced=True)

    assert engine.report()["samba_mount"]["state"] == "installed"


SWITCHER_CATALOG = {
    "modules": {
        "cc_switch": {
            "title": "cc-switch",
            "kind": "switcher",
            "entry": {"binary": "cc-switch", "package_kind": "tar_binary"},
            "verify": "",
            "package": "cc_switch",
        }
    },
    "services": [],
}


def test_a_switcher_order_unpacks_the_handed_archive():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches))
    engine._catalog = dict(SWITCHER_CATALOG)
    installs: list = []
    engine._switcher.install = lambda resolved, path: installs.append(path)
    engine._switcher.verify = lambda resolved: bool(installs)

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "cc_switch",
                "action": "install",
                "artifact_key": "cc_switch-linux-amd64-abcd",
                "package_kind": "tar_binary",
            }
        ],
    )
    engine._reconcile()

    assert fetches == ["cc_switch-linux-amd64-abcd"]
    assert len(installs) == 1
    assert engine.results()[0]["state"] == "done"


def test_a_switcher_uninstall_deletes_the_cli():
    engine = bare_engine()
    engine._catalog = dict(SWITCHER_CATALOG)
    removed: list = []
    engine._switcher.uninstall = lambda resolved: removed.append(True)
    engine._switcher.verify = lambda resolved: not removed

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "cc_switch", "action": "uninstall"}],
    )
    engine._reconcile()

    assert removed == [True]
    assert engine.results()[0]["state"] == "done"
