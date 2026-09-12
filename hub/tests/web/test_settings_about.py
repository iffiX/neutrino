"""The About payload: one version per piece of software the hub carries.

The panel is where an operator reads what is on the box, so what these pin is
that every carried component answers with a version of its own — the panel,
xray, the AI gateway, the interpreter, and the geodata each database is
pinned to — and that an xray that is not installed says so rather than
answering blank.
"""

import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
from neutrino_hub.modules.xray.constants import XRAY_GEODATA
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.routers import settings as settings_router

XRAY_OUTPUT = "Xray 25.8.3 (Xray, Penetrates Everything.) Custom\nA unified platform\n"


def about_payload(monkeypatch, xray_stdout: str = XRAY_OUTPUT) -> dict:
    """Read /about with xray's own output stubbed."""
    monkeypatch.setattr(
        settings_router,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=xray_stdout),
    )
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[require_session] = lambda: None
    with TestClient(app) as client:
        response = client.get("/api/settings/about")
    assert response.status_code == 200, response.text
    return response.json()


def test_every_carried_component_reports_a_version(monkeypatch):
    payload = about_payload(monkeypatch)

    carried = [
        "gateway_version",
        "xray_version",
        "cliproxyapi_version",
        "python_version",
        "geodata_version",
    ]
    assert all(payload[field] != "" for field in carried)


def test_the_ai_gateway_reports_the_version_the_package_pins(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["cliproxyapi_version"] == CLIPROXYAPI_VERSION


def test_the_interpreter_is_the_one_running_the_panel(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["python_version"] == sys.version.split()[0]


def test_the_geodata_baseline_names_the_release_behind_each_database(monkeypatch):
    payload = about_payload(monkeypatch)

    for name, entry in XRAY_GEODATA.items():
        release = entry["url"].rsplit("/", 2)[-2]
        assert name.removesuffix(".dat") in payload["geodata_version"]
        assert release in payload["geodata_version"]


def test_xray_answers_with_its_first_line(monkeypatch):
    payload = about_payload(monkeypatch)

    assert payload["xray_version"] == XRAY_OUTPUT.splitlines()[0]


def test_an_absent_xray_binary_is_reported_not_blank(monkeypatch):
    payload = about_payload(monkeypatch, xray_stdout="")

    assert payload["xray_version"] == "not installed"


def test_the_hub_credits_every_component_it_carries(monkeypatch):
    """The binaries in the hub package first, at the exact tag each was
    built from; the modules a manifest licenses after them."""
    from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_VERSION
    from neutrino_hub.modules.easytier.constants import EASYTIER_VERSION
    from neutrino_hub.modules.netbird.constants import NETBIRD_VERSION
    from neutrino_hub.modules.xray.constants import XRAY_VERSION

    credits = settings_router._acknowledgements()
    by_name = {credit.name: credit for credit in credits}

    assert [credit.name for credit in credits[:4]] == [
        "Xray-core",
        "CLIProxyAPI",
        "NetBird",
        "EasyTier",
    ]
    assert by_name["Xray-core"].version == XRAY_VERSION
    assert by_name["Xray-core"].corresponding_source.endswith(f"/tree/v{XRAY_VERSION}")
    assert by_name["CLIProxyAPI"].version == CLIPROXYAPI_VERSION
    assert by_name["NetBird"].version == NETBIRD_VERSION
    assert by_name["NetBird"].license == "BSD-3-Clause"
    assert by_name["EasyTier"].version == EASYTIER_VERSION
    assert by_name["EasyTier"].license == "LGPL-3.0"
    assert "Gitea" in by_name
