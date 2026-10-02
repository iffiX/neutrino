"""``nhub status``: every unit on Linux, the one service elsewhere."""

from neutrino_hub.cli import status as status_module
from neutrino_hub.system.process_control import ServiceStatus


class _Controller:
    def __init__(self, is_web_active: bool):
        self.is_web_active = is_web_active

    def status_all(self):
        return [
            ServiceStatus("xray", "neutrino_hub_xray.service", True, True, True),
            ServiceStatus(
                "web", "neutrino_hub_web.service", True, self.is_web_active, True
            ),
            ServiceStatus(
                "netbird", "neutrino_hub_netbird.service", False, False, False
            ),
        ]


def test_linux_prints_one_line_per_unit(monkeypatch, capsys):
    monkeypatch.setattr(status_module, "is_linux", lambda: True)
    monkeypatch.setattr(status_module, "process_controller", lambda: _Controller(True))
    monkeypatch.setattr(status_module.sys, "argv", ["nhub status"])

    assert status_module.main() == 0
    output = capsys.readouterr().out
    assert "xray: running, enabled" in output
    assert "netbird: not installed" in output


def test_linux_with_the_panel_down_exits_one(monkeypatch):
    monkeypatch.setattr(status_module, "is_linux", lambda: True)
    monkeypatch.setattr(status_module, "process_controller", lambda: _Controller(False))
    monkeypatch.setattr(status_module.sys, "argv", ["nhub status"])

    assert status_module.main() == 1


def test_macos_and_windows_name_the_one_service(hub_service, monkeypatch, capsys):
    monkeypatch.setattr(status_module.sys, "argv", ["nhub status"])

    assert status_module.main() == 1
    assert "hub service: stopped" in capsys.readouterr().out
    hub_service.is_running = True
    assert status_module.main() == 0
