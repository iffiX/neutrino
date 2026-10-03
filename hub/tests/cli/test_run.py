"""`nhub run --only-web`: the servers one process runs, and their ports.

The panel is served over HTTP on ``listen_port`` and over HTTPS on
``https_listen_port`` whatever ``is_https_enabled`` says, and the agent
channel on its own TLS port. The HTTPS listener's TLS context is the one a
renewal loads the new certificate into.
"""

import argparse
import json
from types import SimpleNamespace

import pytest

from neutrino_hub.cli import run
from neutrino_hub.web.constants import WEB_DEFAULT_HTTPS_LISTEN_PORT

TLS = {"ssl_certfile": "/state/cert.pem", "ssl_keyfile": "/state/key.pem"}


class FakeConfig:
    """A uvicorn configuration that records what it was given."""

    def __init__(self, application, **keywords):
        self.application = application
        self.keywords = keywords
        self.ssl = None

    def load(self):
        if self.keywords.get("ssl_certfile"):
            self.ssl = f"context for port {self.keywords['port']}"


class FakeServer:
    def __init__(self, config):
        self.config = config


@pytest.fixture
def served(monkeypatch):
    """Run ``_serve_panel`` with every effect recorded instead of made."""
    recorded = {"servers": [], "watched": []}

    def serve_together(servers):
        recorded["servers"] = servers

    def asyncio_run(awaited):
        return awaited

    monkeypatch.setattr(
        run,
        "uvicorn",
        SimpleNamespace(Config=FakeConfig, Server=FakeServer, run=None),
    )
    monkeypatch.setattr(run, "_serve_together", serve_together)
    monkeypatch.setattr(run.asyncio, "run", asyncio_run)
    monkeypatch.setattr(run, "ensure_hub_identity", lambda: None)
    monkeypatch.setattr(run, "resolve_management_key", lambda: "key")
    monkeypatch.setattr(run, "_agent_key", lambda: "/state/agent_key.pem")
    monkeypatch.setattr(run, "_configured_port", lambda: 80)
    monkeypatch.setattr(run, "_configured_https_port", lambda: 443)
    monkeypatch.setattr(run, "_configured_agent_port", lambda: 8443)
    monkeypatch.setattr(run, "watch_served_context", recorded["watched"].append)
    return recorded


def arguments(port=None) -> argparse.Namespace:
    return argparse.Namespace(host="0.0.0.0", port=port, reload=False)


def test_three_servers_each_on_its_own_port(served, monkeypatch):
    monkeypatch.setattr(run, "_panel_certificate", lambda: dict(TLS))

    assert run._serve_panel(arguments()) == 0

    configs = [server.config for server in served["servers"]]
    assert [config.application for config in configs] == [
        run.APPLICATION_PATH,
        run.APPLICATION_PATH,
        run.AGENT_APPLICATION_PATH,
    ]
    assert [config.keywords["port"] for config in configs] == [80, 443, 8443]


def test_only_the_https_and_agent_ports_speak_tls(served, monkeypatch):
    monkeypatch.setattr(run, "_panel_certificate", lambda: dict(TLS))

    run._serve_panel(arguments())

    http, https, agent = (server.config.keywords for server in served["servers"])
    assert "ssl_certfile" not in http
    assert https["ssl_certfile"] == TLS["ssl_certfile"]
    assert https["ssl_keyfile"] == TLS["ssl_keyfile"]
    assert agent["ssl_certfile"] == str(run.WEB_AGENT_TLS_CERT_PATH)


def test_the_https_context_is_the_one_a_renewal_reloads(served, monkeypatch):
    monkeypatch.setattr(run, "_panel_certificate", lambda: dict(TLS))

    run._serve_panel(arguments())

    assert served["watched"] == ["context for port 443"]


def test_no_certificate_serves_http_and_the_agent_port(served, monkeypatch):
    monkeypatch.setattr(run, "_panel_certificate", dict)

    run._serve_panel(arguments())

    ports = [server.config.keywords["port"] for server in served["servers"]]
    assert ports == [80, 8443]
    assert served["watched"] == []


def test_an_https_port_that_is_the_http_port_is_not_served(served, monkeypatch, capsys):
    monkeypatch.setattr(run, "_panel_certificate", lambda: dict(TLS))
    monkeypatch.setattr(run, "_configured_https_port", lambda: 80)

    run._serve_panel(arguments())

    ports = [server.config.keywords["port"] for server in served["servers"]]
    assert ports == [80, 8443]
    assert '"code": "port_already_in_use"' in capsys.readouterr().err


def test_the_command_line_port_moves_the_http_port_alone(served, monkeypatch):
    monkeypatch.setattr(run, "_panel_certificate", lambda: dict(TLS))

    run._serve_panel(arguments(port=8080))

    ports = [server.config.keywords["port"] for server in served["servers"]]
    assert ports == [8080, 443, 8443]


def settings_file(tmp_path, monkeypatch, content: dict):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    path = tmp_path / "web" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def test_a_written_https_port_is_read_back(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"https_listen_port": 8444})

    assert run._configured_https_port() == 8444


def test_a_settings_file_without_the_https_port_gets_the_default(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"listen_port": 80})

    assert run._configured_https_port() == WEB_DEFAULT_HTTPS_LISTEN_PORT


class _Controller:
    """The supervised controller, recording what the service asked of it."""

    def __init__(self):
        self.asked: list = []

    def supervise(self, start_lines):
        self.asked.append(("supervise", sorted(start_lines)))

    def shutdown(self):
        self.asked.append(("shutdown",))


@pytest.fixture
def service_roots(monkeypatch, tmp_path):
    for name in ("UTILS_LOG_ROOT", "UTILS_RUNTIME_ROOT", "UTILS_STATE_ROOT"):
        monkeypatch.setattr(run, name, tmp_path / name.lower())
    monkeypatch.setattr(run, "CLIPROXYAPI_DIR", tmp_path / "state" / "cliproxyapi")
    return tmp_path


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_the_service_serves_the_panel_and_supervises_the_children(
    monkeypatch, service_roots, system
):
    controller = _Controller()
    monkeypatch.setattr(run.sys, "platform", system)
    monkeypatch.setattr(run, "process_controller", lambda: controller)
    monkeypatch.setattr(
        run, "_serve_panel", lambda arguments: controller.asked.append(("panel",)) or 0
    )

    assert run._supervise(argparse.Namespace()) == 0
    assert controller.asked == [
        ("supervise", ["cliproxyapi", "netbird", "xray"]),
        ("panel",),
        ("shutdown",),
    ]
    assert (service_roots / "utils_runtime_root").is_dir()


def test_the_children_stop_when_the_panel_fails(monkeypatch, service_roots):
    controller = _Controller()
    monkeypatch.setattr(run.sys, "platform", "darwin")
    monkeypatch.setattr(run, "process_controller", lambda: controller)

    def failing(arguments):
        raise OSError("port taken")

    monkeypatch.setattr(run, "_serve_panel", failing)

    with pytest.raises(OSError):
        run._supervise(argparse.Namespace())
    assert controller.asked[-1] == ("shutdown",)


def test_the_proxy_core_starts_with_its_rendered_configuration_and_geodata():
    line = run.child_start_lines()["xray"]

    assert line.argv == [run.XRAY_BINARY, "run", "-config", str(run.XRAY_CONFIG_PATH)]
    assert line.env == {run.XRAY_ASSET_ENV: str(run.XRAY_ASSET_DIR)}


def test_the_ai_gateway_starts_in_its_own_directory():
    line = run.child_start_lines()["cliproxyapi"]

    assert line.argv[1:] == [
        "--config",
        str(run.UTILS_GENERATED_DIR / run.CLIPROXYAPI_GENERATED_NAME),
    ]
    assert line.cwd == str(run.CLIPROXYAPI_DIR)


@pytest.mark.parametrize(
    ("system", "address"),
    [
        ("darwin", "unix:///var/run/neutrino/hub/netbird.sock"),
        ("win32", "tcp://127.0.0.1:41732"),
    ],
)
def test_netbird_runs_on_the_hubs_own_address_and_log(monkeypatch, system, address):
    from pathlib import Path

    monkeypatch.setattr(run.sys, "platform", system)
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_RUNTIME_ROOT", Path("/var/run/neutrino/hub")
    )
    monkeypatch.setattr(run, "UTILS_STATE_ROOT", Path("/state"))
    monkeypatch.setattr(run, "UTILS_LOG_ROOT", Path("/log"))

    line = run.child_start_lines()["netbird"]

    assert line.argv[1:] == [
        "service",
        "run",
        "--config",
        str(Path("/state/netbird/config.json")),
        "--log-file",
        str(Path("/log/netbird.log")),
        "--daemon-addr",
        address,
    ]
    assert line.log_name == "netbird_console"


def test_the_only_forms_are_refused_outside_linux(monkeypatch, capsys):
    monkeypatch.setattr(run.sys, "platform", "darwin")
    monkeypatch.setattr(run.sys, "argv", ["nhub run", "--only-xray"])

    assert run.main() == 2
    assert "systemd unit" in capsys.readouterr().err


def test_linux_without_only_supervises_as_it_always_did(monkeypatch):
    started = []
    monkeypatch.setattr(run, "_start_child", lambda name: started.append(name))
    monkeypatch.setattr(run, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(run, "_serve_panel", lambda arguments: 0)
    monkeypatch.setattr(
        run, "process_controller", lambda: pytest.fail("no controller on Linux")
    )

    assert run._supervise(argparse.Namespace()) == 0
    assert started == ["xray", "cliproxyapi"]


def test_outside_linux_the_service_waits_for_setup_instead_of_exiting(monkeypatch):
    answers = iter([False, False, False, True])
    naps = []
    monkeypatch.setattr(run, "is_linux", lambda: False)
    monkeypatch.setattr(run, "_is_set_up", lambda: next(answers))
    monkeypatch.setattr(run.time, "sleep", naps.append)
    monkeypatch.setattr(run, "_supervise", lambda arguments: 0)
    monkeypatch.setattr(run.sys, "argv", ["nhub-run"])
    assert run.main() == 0
    assert naps == [run.PLATFORM_SETUP_POLL_S, run.PLATFORM_SETUP_POLL_S]


def test_on_linux_a_hub_not_set_up_exits_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(run, "is_linux", lambda: True)
    monkeypatch.setattr(run, "_is_set_up", lambda: False)
    monkeypatch.setattr(run.sys, "argv", ["nhub-run"])
    assert run.main() == 1
    assert "nhub setup" in capsys.readouterr().err
