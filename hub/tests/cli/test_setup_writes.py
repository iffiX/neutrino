"""What `nhub setup` writes into `config/` from what the wizard collected.

This is the layer between the two that neither of them tests: the wizard
returns answers and is checked on those, the renderers are checked on the
files, and the step that turns one into the other was found broken by a VM
install rather than by anything here.
"""

import pytest

from neutrino_hub.cli import setup, wizard
from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR

# A share link the parser accepts, made up: example.com, and the password
# inside the base64 is the words "s3cret-password".
SHARE_LINK = (
    "ss://YWVzLTI1Ni1nY206czNjcmV0LXBhc3N3b3Jk@hk.example.com:5800#HK"  # scan: allow
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` seeded from the examples, as `_step_config_files` leaves it."""
    for name in ("xray/nodes.json", "xray/routing.json"):
        source = UTILS_EXAMPLES_DIR / name.replace(".json", ".example.json")
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_the_nodes_replace_the_examples_and_keep_their_settings(config_dir):
    """Building a fresh list dropped the balancer strategy and the probe, and
    the constructor refused it — on a VM, not here."""
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(
        wizard.WizardProxy(is_enabled=True, nodes=(parse_share_link(SHARE_LINK),))
    )

    nodes = read_config("xray/nodes.json")
    assert [node["id"] for node in nodes["nodes"]] == ["hk"]
    assert nodes["balancer"]["strategy"], "the example's strategy survived"


def test_every_proxy_answer_reaches_the_routing_file(config_dir):
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(
        wizard.WizardProxy(
            is_enabled=True,
            nodes=(parse_share_link(SHARE_LINK),),
            is_local=True,
            is_socks_proxy_enabled=True,
            socks_proxy_port=1081,
            is_socks_direct_enabled=True,
            socks_direct_port=1088,
        )
    )

    routing = read_config("xray/routing.json")
    assert routing["is_proxy_enabled"] is True
    assert routing["is_local_proxy_enabled"] is True
    # Two questions, one list: each answered port becomes a listener, and
    # which way its traffic leaves is what it carries.
    assert routing["socks_ports"] == [
        {"port": 1081, "is_proxied": True},
        {"port": 1088, "is_proxied": False},
    ]


def test_skipping_the_proxy_empties_the_example_nodes(config_dir):
    """The example ships two nodes with placeholder keys, which xray refuses."""
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(wizard.WizardProxy())

    assert read_config("xray/nodes.json")["nodes"] == []
    assert read_config("xray/routing.json")["is_proxy_enabled"] is False


# --- a step that fails without ending the run ---


def test_the_box_survives_the_two_steps_it_is_a_gateway_without():
    """Hardening SSH and installing the AI gateway are both worth having and
    neither is what makes this a gateway. A first run that stops at step two
    over one of them leaves a machine with nothing."""
    assert setup._step_fail2ban in setup.SETUP_STEPS_THE_BOX_SURVIVES
    assert setup._step_cliproxyapi in setup.SETUP_STEPS_THE_BOX_SURVIVES


def test_every_other_step_still_ends_the_run():
    """The ones the box is not a gateway without: its interfaces, its
    firewall, its own configuration."""
    for step in (
        setup._step_config_files,
        setup._step_interfaces,
        setup._step_render_all,
        setup._step_systemd_units,
    ):
        assert step not in setup.SETUP_STEPS_THE_BOX_SURVIVES


def test_hardening_ssh_never_restarts_the_unit_it_just_started(monkeypatch, tmp_path):
    """Starting fail2ban with `--now` and then restarting it races the unit
    against itself: the restart's stop half runs `fail2ban-client stop` before
    the server it just started has made its socket, that exits 255, and
    systemd falls back to signalling and waits out the stop timeout — a minute
    of a first run spent on a race nobody needed."""
    commands: list = []
    monkeypatch.setattr(
        setup, "run", lambda command, **keywords: commands.append(command) or _Ran()
    )
    monkeypatch.setattr(setup, "SYSTEM_FAIL2BAN_JAIL_PATH", tmp_path / "jail.conf")

    setup._step_fail2ban(_SilentReporter())

    verbs = [command[1] for command in commands if command[0] == "systemctl"]
    assert "restart" not in verbs
    assert "--now" not in [word for command in commands for word in command]


class _Ran:
    is_success = True
    stdout = ""


class _SilentReporter:
    def note(self, text: str) -> None:
        pass

    def banner(self, text: str) -> None:
        pass

    def blank(self) -> None:
        pass

    def start(self, description: str) -> None:
        pass

    def done(self, note: str = "") -> None:
        pass


# --- a run that outlives the session watching it ---


def test_the_run_ignores_a_hang_up_once_it_starts_changing_the_machine(monkeypatch):
    """A first run reconfigures the interface it is often watched over. A
    hang-up from that must not end it: a run stopped halfway leaves a box that
    is neither what it was nor what it was asked to be, and nobody is there to
    see which."""
    import signal

    handled: list = []
    monkeypatch.setattr(
        signal, "signal", lambda number, action: handled.append((number, action))
    )
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(setup, "_start_panel", lambda: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    setup._setup(_SilentReporter(), [], _NoAnswers())

    assert (signal.SIGHUP, signal.SIG_IGN) in handled


def test_the_log_is_named_before_the_first_step(monkeypatch):
    """Somebody who loses the session at step nine needs to have already read
    where to look."""
    said: list = []
    reporter = _SilentReporter()
    reporter.note = said.append
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(setup, "_start_panel", lambda: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    setup._setup(reporter, [], _NoAnswers())

    assert any(str(setup.SETUP_LOG_PATH) in line for line in said)
    assert any("will finish on its own" in line for line in said)


class _NoAnswers:
    password = "x"
    services: tuple = ()
