"""Setup's step table on each system.

Linux runs every step. macOS and Windows skip the steps that guard SSH,
install units and take the interfaces over, check the carried programs in
place of system packages, make directories and no account, and start the
hub's one service once, after the password and before this machine's agent.
"""

import pytest

from neutrino_hub import edition
from neutrino_hub.cli import setup
from tests.cli.test_setup_local_agent import FakeReporter

# The proxy core's step and its unit, where the tree carries the proxy.
XRAY = ["xray"] if edition.has_feature("proxy") else []
EVERY_STEP = [
    "required_packages",
    "fail2ban",
    "users_and_dirs",
    "python_env",
    *[f"{name}_core" for name in XRAY],
    "config_files",
    "agent_tls",
    "panel_tls",
    "systemd_units",
    "interfaces",
    "render_all",
    "enable_services",
    "start_services",
    "overlay",
    "cliproxyapi",
]
LINUX_ONLY = ("fail2ban", "systemd_units", "interfaces")
# Outside Linux the one service starts after the table, not inside it.
NOT_OUTSIDE_LINUX = (*LINUX_ONLY, "start_services")


class FakeController:
    """The process controller, recording each verb."""

    def __init__(self, *, is_installed: bool = True, refusal=None):
        self.asked: list = []
        self.is_installed = is_installed
        self.refusal = refusal

    def status(self, name):
        class Status:
            is_installed = self.is_installed
            is_enabled = False

        return Status()

    def enable(self, name):
        self.asked.append(("enable", name))

    def control(self, name, action):
        self.asked.append((action, name))

    def restart(self, name):
        self.asked.append(("restart", name))
        if self.refusal is not None:
            raise self.refusal


@pytest.fixture
def controller(monkeypatch):
    fake = FakeController()
    monkeypatch.setattr(setup, "process_controller", lambda: fake)
    return fake


def _run_steps() -> list:
    return [
        step_id
        for step_id, _, step in setup.CORE_STEPS
        if step not in setup._skipped_steps()
    ]


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("linux", EVERY_STEP),
        ("darwin", [step for step in EVERY_STEP if step not in NOT_OUTSIDE_LINUX]),
        ("win32", [step for step in EVERY_STEP if step not in NOT_OUTSIDE_LINUX]),
    ],
)
def test_the_steps_each_system_runs(monkeypatch, system, expected):
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)

    assert _run_steps() == expected


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_a_development_root_also_skips_the_service_steps(monkeypatch, system):
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: True)

    steps = _run_steps()

    for skipped in (*LINUX_ONLY, "enable_services", "start_services"):
        assert skipped not in steps


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_the_carried_programs_are_checked_not_system_packages(
    monkeypatch, tmp_path, system
):
    programs = [tmp_path / name for name in ("xray", "netbird")]
    for program in programs:
        program.write_text("")
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "SETUP_CARRIED_PROGRAMS", tuple(programs))
    monkeypatch.setattr(
        setup.package_manager, "current", lambda: pytest.fail("no package manager")
    )

    assert setup._step_required_packages(FakeReporter()) == "2 present"


def test_a_missing_carried_program_asks_for_a_reinstall(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup, "SETUP_CARRIED_PROGRAMS", (tmp_path / "xray",))

    with pytest.raises(FileNotFoundError, match="reinstall"):
        setup._step_required_packages(FakeReporter())


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_directories_are_made_and_no_account(monkeypatch, tmp_path, system):
    monkeypatch.setattr(setup.sys, "platform", system)
    for name in ("UTILS_CONFIG_DIR", "UTILS_GENERATED_DIR"):
        monkeypatch.setattr(setup, name, tmp_path / name.lower())
    if edition.has_feature("proxy"):
        monkeypatch.setattr(
            "neutrino_hub.modules.xray.setup_part.XRAY_GEODATA_DIR",
            tmp_path / "geodata",
        )
    monkeypatch.setattr(setup, "UTILS_LOG_DIR", tmp_path / "log")
    monkeypatch.setattr(setup, "run", lambda *a, **k: pytest.fail("no useradd"))

    assert setup._step_users_and_dirs(FakeReporter()) == "created directories"
    assert (tmp_path / "log").is_dir()
    assert setup._step_users_and_dirs(FakeReporter()) == "present"


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_the_core_children_are_enabled_through_the_controller(
    monkeypatch, controller, system
):
    monkeypatch.setattr(setup.sys, "platform", system)

    setup._step_enable_services(FakeReporter())

    assert controller.asked == [("enable", name) for name in [*XRAY, "cliproxyapi"]]


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_children_the_stopped_service_does_not_run_yet_are_enabled(monkeypatch, system):
    controller = FakeController(is_installed=False)
    monkeypatch.setattr(setup, "process_controller", lambda: controller)
    monkeypatch.setattr(setup.sys, "platform", system)

    setup._step_enable_services(FakeReporter())

    assert controller.asked == [("enable", name) for name in [*XRAY, "cliproxyapi"]]


def test_linux_enables_its_core_units_through_the_controller(monkeypatch, controller):
    monkeypatch.setattr(setup.sys, "platform", "linux")

    setup._step_enable_services(FakeReporter())

    assert controller.asked == [
        ("enable", name) for name in ["router", *XRAY, "dnsmasq", "web"]
    ]


def test_the_panel_starts_through_the_controller(monkeypatch, controller):
    monkeypatch.setattr(setup.sys, "platform", "linux")
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    reporter = FakeReporter()

    assert setup._start_panel(reporter)
    assert controller.asked == [("restart", "web")]
    assert reporter.started == []


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_outside_linux_the_one_service_starts_as_a_step_of_its_own(
    monkeypatch, controller, system
):
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    reporter = FakeReporter()

    assert setup._start_panel(reporter)
    assert controller.asked == [("restart", "web")]
    assert reporter.started == [("Starting the hub's service", "start_services")]
    assert reporter.done_notes == ["started the hub's service"]


def test_a_service_that_will_not_start_fails_its_step(monkeypatch):
    controller = FakeController(refusal=OSError("the manager refused"))
    monkeypatch.setattr(setup, "process_controller", lambda: controller)
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    reporter = FakeReporter()

    assert not setup._start_panel(reporter)
    assert reporter.failures


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_outside_linux_the_service_starts_once_after_the_steps_and_the_password(
    monkeypatch, system
):
    order: list = []
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(
        setup, "store_password", lambda password: order.append("password")
    )
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://127.0.0.1:8080")
    monkeypatch.setattr(
        setup.RouterStateController,
        "write_system_firewall",
        lambda self: order.append("firewall") or [],
    )
    monkeypatch.setattr(
        setup, "_start_panel", lambda reporter: order.append("service") or True
    )
    monkeypatch.setattr(
        setup,
        "_install_local_agent",
        lambda password, reporter: order.append("local_agent"),
    )
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)
    steps = [
        (step_id, description, _recorder(order, step_id))
        for step_id, description, step in setup.CORE_STEPS
        if step not in setup._skipped_steps()
    ]

    assert setup._setup(_QuietReporter(), steps, _Answers()) == 0
    assert order[-7:] == [
        "enable_services",
        "overlay",
        "cliproxyapi",
        "password",
        "firewall",
        "service",
        "local_agent",
    ]
    assert order.count("service") == 1


def _recorder(order: list, step_id: str):
    def step(reporter):
        order.append(step_id)
        return ""

    return step


class _QuietReporter(FakeReporter):
    def banner(self, text):
        pass

    def blank(self):
        pass


class _Answers:
    password = "x"
    is_https_enabled = False


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_rendering_runs_nhub_apply_itself(monkeypatch, system):
    commands = []

    class Result:
        is_success = True

    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(
        setup, "run", lambda command, **k: commands.append(command) or Result()
    )

    setup._step_render_all(FakeReporter())

    assert commands[0][-2:] == ["apply", "--skip-apply"]
    assert "neutrino_hub.cli.entry" in commands[0]


@pytest.mark.parametrize(
    ("system", "family", "install", "agent"),
    [
        (
            "darwin",
            "pkg",
            ["installer", "-pkg", "/cache/agent.pkg", "-target", "/"],
            "/usr/local/bin/nagent",
        ),
        (
            "win32",
            "msi",
            ["msiexec", "/i", "/cache/agent.msi", "/qn", "/norestart"],
            "C:\\Program Files\\Neutrino\\agent\\nagent.exe",
        ),
    ],
)
def test_the_local_agent_is_installed_by_the_systems_installer(
    monkeypatch, system, family, install, agent
):
    commands = []
    families = []

    class Cache:
        def serves(self, *, family, architecture):
            families.append(family)
            return True

        def package(self, *, family, architecture):
            return f"/cache/agent.{family}"

    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(setup, "machine_architecture", lambda: "amd64")
    monkeypatch.setattr(setup, "AgentPackageCache", Cache)
    monkeypatch.setattr(
        setup, "_enrollment_link", lambda password: ("neutrino://x", "")
    )
    monkeypatch.setattr(setup, "run", lambda command, **k: commands.append(command))
    monkeypatch.setattr(
        setup.package_manager, "current", lambda: pytest.fail("no package manager")
    )
    reporter = FakeReporter()

    setup._install_local_agent("password", reporter)

    assert families == [family]
    assert commands == [install, [agent, "join", "neutrino://x", "--yes"]]
    assert reporter.done_notes == ["installed and joined"]


def test_no_hang_up_signal_on_windows_is_not_a_failure(monkeypatch):
    import signal

    monkeypatch.delattr(signal, "SIGHUP")
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://127.0.0.1:8080")
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    class Reporter(FakeReporter):
        def banner(self, text):
            pass

        def blank(self):
            pass

    class Answers:
        password = "x"
        is_https_enabled = False

    assert setup._setup(Reporter(), [], Answers()) == 0


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_the_browser_opens_through_the_platform(monkeypatch, system):
    opened = []
    monkeypatch.setattr(setup.sys, "platform", system)

    class Platform:
        def open_browser(self, url):
            opened.append(url)
            return True

    monkeypatch.setattr(setup, "hub_platform", Platform)

    assert setup._open_browser("http://127.0.0.1:8080/?token=t")
    assert opened == ["http://127.0.0.1:8080/?token=t"]


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_an_ordinary_account_is_refused(monkeypatch, capsys, system):
    monkeypatch.setattr(setup.sys, "platform", system)
    monkeypatch.setattr(setup.sys, "argv", ["nhub setup"])

    class Platform:
        elevation_word = "an administrator"

        def is_elevated(self):
            return False

        def elevation_hint(self, arguments):
            return f"nhub {arguments}"

    monkeypatch.setattr(setup, "hub_platform", Platform)

    assert setup.main() == 1
    assert "an administrator" in capsys.readouterr().err
