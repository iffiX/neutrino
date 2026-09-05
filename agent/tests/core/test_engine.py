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

DEB_ENTRY = {"package_kind": "deb", "uninstall": "apt-get remove -y todesk"}

CATALOG = {
    "modules": {
        "todesk": {
            "title": "ToDesk",
            "kind": "package",
            "entry": DEB_ENTRY,
            "verify": "",
            "package": "todesk",
        }
    },
    "services": [],
}


class FakePlatform(AgentPlatform):
    """A platform that records installs and refuses nothing else."""

    os_name = "linux"

    def __init__(self, *, install_error=None):
        self.installs: list = []
        self.removals: list = []
        self._install_error = install_error

    def install_package(self, path, *, package_kind, entry):
        self.installs.append((package_kind, entry))
        if self._install_error is not None:
            raise self._install_error

    def uninstall_package(self, command):
        self.removals.append(command)


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

    from neutrino_agent.modules.openssh import OpensshModuleReconciler
    from neutrino_agent.modules.package import PackageModuleRunner

    platform = platform if platform is not None else FakePlatform()
    engine._fetch_artifact = fetch_artifact
    engine._package = PackageModuleRunner(
        platform=platform, log=engine._collect, publish=engine._publish
    )
    engine._openssh = OpensshModuleReconciler(
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
                "module": "todesk",
                "action": "install",
                "artifact_key": "todesk-linux-debian-amd64-aaaa",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    assert fetches == ["todesk-linux-debian-amd64-aaaa"]
    assert platform.installs == [("deb", DEB_ENTRY)]
    result = engine.results()[0]
    assert result["id"] == "order-1"
    assert result["state"] == "done"
    assert result["output"] == ""


def test_an_install_the_machine_cannot_confirm_is_failed_not_latched():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "todesk",
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
                "module": "todesk",
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
        return {"code": "vendor_served_a_page", "params": {"size": 2048}}

    engine = bare_engine(fetch_artifact=refuse, verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "todesk",
                "action": "install",
                "artifact_key": "key",
                "package_kind": "deb",
            }
        ],
    )
    engine._reconcile()

    result = engine.results()[0]
    assert result["code"] == "vendor_served_a_page"
    assert result["params"] == {"size": 2048}


def test_a_removal_is_run_and_confirmed():
    platform = FakePlatform()
    engine = bare_engine(platform=platform, verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "todesk", "action": "remove"}],
    )
    engine._reconcile()

    assert platform.removals == ["apt-get purge -y todesk"]
    assert engine.results()[0]["state"] == "done"


def test_a_removal_that_did_not_take_is_reported_failed():
    engine = bare_engine(verified=[True])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[{"id": "order-1", "module": "todesk", "action": "remove"}],
    )
    engine._reconcile()

    assert engine.results()[0]["code"] == "remove_unconfirmed"


def test_no_tick_ever_reruns_a_failed_order():
    fetches: list = []
    engine = bare_engine(fetch_artifact=landing_fetch(fetches), verified=[False])
    order = {
        "id": "order-1",
        "module": "todesk",
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
        "module": "todesk",
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
        "module": "todesk",
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
    engine._catalog = {"modules": {"todesk": {"kind": "package", "entry": None}}}

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "todesk",
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
        orders=[{"id": "order-1", "module": "todesk", "action": "reticulate"}],
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
                "module": "todesk",
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
    assert platform.removals == []
    assert engine.report()["todesk"]["state"] == "installed"


def test_a_module_with_no_build_here_is_reported_unsupported_not_failed():
    engine = bare_engine()
    engine._catalog = {"modules": {"todesk": {"kind": "package", "entry": None}}}

    engine._refresh(is_forced=True)

    assert engine.report()["todesk"] == {
        "state": "unsupported",
        "code": "no_platform_build",
        "params": {},
        "is_active": False,
    }


def test_a_kind_the_engine_does_not_run_is_reported_as_unknown():
    engine = bare_engine()
    engine._catalog = {"modules": {"thing": {"kind": "ai_tools", "entry": {}}}}

    engine._refresh(is_forced=True)

    assert engine.report()["thing"] == {
        "state": "unknown",
        "code": "unknown_kind",
        "params": {"kind": "ai_tools"},
        "is_active": False,
    }


def test_an_absent_capability_reports_unsupported_platform():
    engine = bare_engine(platform=AgentPlatform())
    engine._catalog = {"modules": {"openssh_server": {"kind": "openssh", "entry": {}}}}

    engine._refresh(is_forced=True)

    assert engine.report()["openssh_server"] == {
        "state": "failed",
        "code": "unsupported_platform",
        "params": {},
        "is_active": False,
    }


def test_the_engine_holds_no_failure_memory():
    engine = bare_engine(fetch_artifact=landing_fetch([]), verified=[False])

    engine.update(
        catalog=None,
        catalog_hash="abc",
        orders=[
            {
                "id": "order-1",
                "module": "todesk",
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
