"""The module engine's own judgments, before any reconciler runs."""

import threading

from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.modules.openssh import OpensshModuleReconciler
from neutrino_agent.platforms.base import AgentPlatform
from tests.conftest import discard


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
