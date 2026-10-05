"""`nhub open`: the elevated step that starts the service and says where it
answers, and the browser opened as the person.

The platform, the service and the browser are fakes. What is pinned is that
the service is started only when it is stopped, that the setup token rides
the address only before setup, that an unprivileged run asks for the
elevated step and opens what that step wrote, and that the step itself
refuses to run without privilege.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from neutrino_hub.cli import open as open_command


class FakePlatform:
    """A platform that records what it was asked."""

    elevation_word = "root"

    def __init__(self, *, is_elevated: bool, step_address: str = ""):
        self._is_elevated = is_elevated
        self.step_address = step_address
        self.elevated: list = []
        self.opened: list = []
        self.is_opening = True

    def is_elevated(self) -> bool:
        return self._is_elevated

    def run_elevated(self, arguments: list) -> bool:
        self.elevated.append(arguments)
        if not self.step_address:
            return False
        Path(arguments[arguments.index("--output") + 1]).write_text(
            self.step_address + "\n"
        )
        return True

    def open_browser(self, url: str) -> bool:
        self.opened.append(url)
        return self.is_opening


class FakeController:
    """The hub's service, running or not."""

    def __init__(self, *, is_running: bool):
        self.is_running = is_running
        self.asked: list = []

    def status(self, name):
        return SimpleNamespace(is_active=self.is_running)

    def control(self, name, action):
        self.asked.append((name, action))
        self.is_running = True


@pytest.fixture
def box(monkeypatch):
    """A hub on port 8080, not set up, with its token."""
    state = SimpleNamespace(
        is_set_up=False, controller=FakeController(is_running=False)
    )
    monkeypatch.setattr(open_command, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(open_command, "process_controller", lambda: state.controller)
    monkeypatch.setattr(open_command, "is_password_set", lambda: state.is_set_up)
    monkeypatch.setattr(open_command, "ensure_setup_token", lambda: "t0ken")
    monkeypatch.setattr(open_command, "_configured_port", lambda: 8080)
    monkeypatch.setattr(open_command, "_reachable_host", lambda: "192.0.2.7")

    def run(*arguments, platform):
        monkeypatch.setattr(open_command, "hub_platform", lambda: platform)
        monkeypatch.setattr(open_command.sys, "argv", ["nhub open", *arguments])
        return open_command.main()

    state.run = run
    return state


def test_with_privilege_the_service_starts_and_the_wizard_opens_with_its_token(box):
    platform = FakePlatform(is_elevated=True)

    assert box.run(platform=platform) == 0

    assert box.controller.asked == [("web", "start")]
    assert platform.opened == ["http://127.0.0.1:8080/?token=t0ken"]
    assert platform.elevated == []


def test_a_set_up_box_opens_the_panel_without_a_token(box):
    box.is_set_up = True
    box.controller.is_running = True
    platform = FakePlatform(is_elevated=True)

    box.run(platform=platform)

    assert box.controller.asked == []
    assert platform.opened == ["http://127.0.0.1:8080/"]


def test_without_privilege_the_elevated_step_runs_and_its_address_opens(box):
    platform = FakePlatform(
        is_elevated=False, step_address="http://127.0.0.1:8080/?token=t0ken"
    )

    assert box.run(platform=platform) == 0

    ((open_word, flag, output_flag, output),) = platform.elevated
    assert (open_word, flag, output_flag) == ("open", "--start-service", "--output")
    assert not Path(output).exists()
    assert platform.opened == ["http://127.0.0.1:8080/?token=t0ken"]
    assert box.controller.asked == []


def test_a_declined_elevated_step_opens_the_default_port_and_says_so(box, capsys):
    platform = FakePlatform(is_elevated=False)

    assert box.run(platform=platform) == 0

    assert platform.opened == ["http://127.0.0.1:8080/"]
    assert "was not started" in capsys.readouterr().err


def test_with_no_browser_the_address_is_printed(box, capsys):
    platform = FakePlatform(is_elevated=True)
    platform.is_opening = False

    box.run(platform=platform)

    assert capsys.readouterr().out.strip() == "http://127.0.0.1:8080/?token=t0ken"


def test_the_elevated_step_starts_the_service_and_writes_the_address(box, tmp_path):
    output = tmp_path / "address"
    output.write_text("")
    platform = FakePlatform(is_elevated=True)

    assert box.run("--start-service", "--output", str(output), platform=platform) == 0

    assert box.controller.asked == [("web", "start")]
    assert output.read_text() == "http://127.0.0.1:8080/?token=t0ken\n"
    assert platform.opened == []


def test_the_elevated_step_refuses_to_run_without_privilege(box):
    platform = FakePlatform(is_elevated=False)

    assert box.run("--start-service", platform=platform) == 2
    assert box.controller.asked == []


def test_a_refused_start_fails_the_elevated_step(box, monkeypatch):
    def refuse(name, action):
        raise open_command.subprocess.CalledProcessError(1, ["systemctl"])

    monkeypatch.setattr(box.controller, "control", refuse)

    assert box.run("--start-service", platform=FakePlatform(is_elevated=True)) == 1


def test_print_names_the_address_another_machine_opens(box, capsys):
    platform = FakePlatform(is_elevated=True)

    assert box.run("--print", platform=platform) == 0

    assert capsys.readouterr().out.strip() == "http://192.0.2.7:8080/?token=t0ken"
    assert box.controller.asked == [("web", "start")]
    assert platform.opened == []


def test_print_without_privilege_carries_no_token(box, capsys):
    platform = FakePlatform(is_elevated=False)

    box.run("--print", platform=platform)

    captured = capsys.readouterr()
    assert captured.out.strip() == "http://192.0.2.7:8080/"
    assert "setup token" in captured.err


def test_a_development_root_starts_no_service(box, monkeypatch):
    monkeypatch.setattr(open_command, "is_dev_root_set", lambda: True)

    box.run(platform=FakePlatform(is_elevated=True))

    assert box.controller.asked == []


def test_the_command_is_offered_without_privilege():
    from neutrino_hub.cli import entry

    assert entry.COMMANDS["open"][0] == "neutrino_hub.cli.open"


# --- the address another machine reaches this one at ---


class RoutedLinks:
    """Link status whose default routes leave by the named devices."""

    routed: tuple = ()

    def gateway_for(self, name):
        return "192.0.2.1" if name in RoutedLinks.routed else None


def reachable(monkeypatch, addresses: dict, stored=None, routed=()) -> str:
    def read(name):
        if stored is None:
            raise FileNotFoundError(name)
        return stored

    RoutedLinks.routed = routed
    monkeypatch.setattr(open_command, "device_addresses", lambda: dict(addresses))
    monkeypatch.setattr(open_command, "read_config", read)
    monkeypatch.setattr(open_command, "RouterLinkStatus", RoutedLinks)
    return open_command._reachable_host()


def test_an_exposed_interface_s_address_comes_first(monkeypatch):
    stored = {
        "mode": "server",
        "interfaces": [
            {"name": "eno1", "is_exposed": False},
            {"name": "eno2", "is_exposed": True},
        ],
    }

    host = reachable(
        monkeypatch,
        {"docker0": "172.17.0.1/16", "eno1": "10.0.0.5/24", "eno2": "192.168.8.5/24"},
        stored=stored,
        routed=("eno1",),
    )

    assert host == "192.168.8.5"


def test_before_setup_the_interface_holding_the_default_route_comes_first(
    monkeypatch,
):
    host = reachable(
        monkeypatch,
        {"docker0": "172.17.0.1/16", "enp3s0": "192.168.8.5/24"},
        routed=("enp3s0",),
    )

    assert host == "192.168.8.5"


def test_with_no_route_the_first_address_the_box_holds_answers(monkeypatch):
    assert reachable(monkeypatch, {"enp3s0": "192.168.8.5/24"}) == "192.168.8.5"


def test_with_no_address_the_hostname_answers(monkeypatch):
    monkeypatch.setattr(open_command.socket, "gethostname", lambda: "hub")

    assert reachable(monkeypatch, {}) == "hub"


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_outside_linux_an_interface_not_named_counts_as_answering(monkeypatch, system):
    """The hidden adapters never reach here: ``device_addresses`` leaves out
    the proxy's TUN and the client's files adapter."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", system)

    host = reachable(monkeypatch, {"Ethernet": "192.168.8.5/24"})

    assert host == "192.168.8.5"
