"""Reconciling one package feature on a device.

The failure this is built around: a manifest whose verify command names the
wrong path leaves a package installed and unconfirmed, and the idle re-check
a minute later reads it as absent and installs it again. Nothing stops that
loop on its own — the download is fifty megabytes and the device repeats it
every minute until somebody looks at the traffic.
"""

import pytest

from neutrino_agent import features
from neutrino_agent.features import FeatureManager

MANIFEST = {
    "name": "todesk",
    "kind": "package",
    "verify": {"linux": "false"},
    "platforms": {"debian": {"url": "https://example.invalid/todesk.deb"}},
}


@pytest.fixture
def reconciler(monkeypatch):
    """One reconciler whose installs are counted and whose verify never
    confirms, which is the shape of the manifest bug."""
    installs: list = []
    monkeypatch.setattr(features, "download", lambda *a, **k: None)
    monkeypatch.setattr(features, "verify_package", lambda *a, **k: None)
    monkeypatch.setattr(
        features,
        "install_package",
        lambda *a, **k: installs.append(1),
    )
    reconciler = FeatureManager.__new__(FeatureManager)
    reconciler._log = lambda *a, **k: None
    reconciler._on_change = None
    reconciler._statuses = {}
    reconciler._unconfirmed = set()
    reconciler._platform = ("linux", "debian", "amd64")
    monkeypatch.setattr(FeatureManager, "_verify", lambda self, manifest: False)
    monkeypatch.setattr(FeatureManager, "_publish", lambda self, name, state: None)
    return reconciler, installs


def entry() -> dict:
    return MANIFEST["platforms"]["debian"]


def test_an_install_whose_verify_never_confirms_runs_once(reconciler):
    subject, installs = reconciler

    first = subject._reconcile_package("todesk", MANIFEST, entry(), True)
    second = subject._reconcile_package("todesk", MANIFEST, entry(), True)
    third = subject._reconcile_package("todesk", MANIFEST, entry(), True)

    assert len(installs) == 1
    assert second == first
    assert third == first
    assert "verify did not confirm" in first["message"]


def test_removing_it_makes_installing_worth_trying_again(reconciler, monkeypatch):
    subject, installs = reconciler
    monkeypatch.setattr(features, "uninstall_package", lambda command: None)
    subject._reconcile_package("todesk", MANIFEST, entry(), True)

    subject._reconcile_package(
        "todesk", MANIFEST, dict(entry(), uninstall="apt-get remove -y todesk"), False
    )
    subject._reconcile_package("todesk", MANIFEST, entry(), True)

    assert len(installs) == 2


def test_an_install_that_does_confirm_is_not_remembered_as_unconfirmed(
    reconciler, monkeypatch
):
    subject, installs = reconciler
    answers = iter([False, True])
    monkeypatch.setattr(
        FeatureManager, "_verify", lambda self, manifest: next(answers, True)
    )

    state = subject._reconcile_package("todesk", MANIFEST, entry(), True)

    assert state["message"] == ""
    assert subject._unconfirmed == set()
