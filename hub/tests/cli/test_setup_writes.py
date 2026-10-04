"""What `nhub setup` writes into `config/` from what the wizard collected.

This is the layer between the two that neither of them tests: the wizard
returns answers and is checked on those, the renderers are checked on the
files, and the step that turns one into the other was found broken by a VM
install rather than by anything here.
"""

import pytest

from neutrino_hub.cli import setup, wizard

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


def test_outside_linux_setup_writes_the_system_firewall_before_the_service(
    elsewhere, monkeypatch
):
    """A Windows box set up had no hub rule until its first exposure change."""
    order: list = []
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(
        setup.RouterStateController,
        "write_system_firewall",
        lambda self: order.append("firewall") or [],
    )
    monkeypatch.setattr(
        setup, "_start_panel", lambda reporter: order.append("service") or True
    )
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    setup._setup(_SilentReporter(), [], _NoAnswers())

    assert order == ["firewall", "service"]


def test_on_linux_setup_leaves_the_firewall_to_the_ruleset(monkeypatch):
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(
        setup.RouterStateController,
        "write_system_firewall",
        lambda self: pytest.fail("Linux has no system firewall pass"),
    )
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    assert setup._setup(_SilentReporter(), [], _NoAnswers()) == 0


def test_the_config_files_step_copies_no_example_record(tmp_path, monkeypatch):
    """`clients.json` once came out of setup naming the example's device id in
    its default permission."""
    monkeypatch.setattr(setup, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup, "CONFIG_FILES", ("clients/clients.json",))
    monkeypatch.setattr(setup, "ensure_hub_identity", lambda: False)

    setup._step_config_files(_SilentReporter())

    written = (tmp_path / "clients" / "clients.json").read_text(encoding="utf-8")
    assert "_example_" not in written


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

    def start(
        self, description: str, code: str = "", params: dict | None = None
    ) -> None:
        pass

    def done(self, note: str = "") -> None:
        pass

    def failed(self, note: str = "") -> None:
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
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
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
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup.wizard, "finish", lambda **keywords: None)

    setup._setup(reporter, [], _NoAnswers())

    assert any(str(setup.UTILS_SETUP_LOG_PATH) in line for line in said)
    assert any("will finish on its own" in line for line in said)


class _NoAnswers:
    password = "x"
    is_https_enabled = False


@pytest.mark.parametrize("is_https", [False, True])
def test_the_panel_settings_carry_the_scheme_asked_for(tmp_path, monkeypatch, is_https):
    from neutrino_hub.utils.json_file import read_config, write_config

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    write_config("web/settings.json", {"listen_port": 8080, "is_https_enabled": True})

    setup._write_panel_settings(8090, 8453, "zh-CN", is_https)

    settings = read_config("web/settings.json")
    assert settings["listen_port"] == 8090
    assert settings["https_listen_port"] == 8453
    assert settings["language"] == "zh-CN"
    assert settings["is_https_enabled"] is is_https


def test_the_panel_certificates_are_made_right_after_the_agent_channels():
    names = [step_id for step_id, _, _ in setup.CORE_STEPS]

    assert names.index("panel_tls") == names.index("agent_tls") + 1
    assert names.index("panel_tls") > names.index("config_files")


def test_an_https_run_hands_over_the_authority_to_install(monkeypatch, tmp_path):
    """The last screen names where to download the authority and its
    fingerprint; an HTTP run names neither."""
    import base64
    import hashlib

    finished: list = []
    der = b"a certificate"
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "https://192.168.8.1")
    monkeypatch.setattr(setup, "_panel_http_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(setup, "authority_der", lambda: der)
    monkeypatch.setattr(setup, "hub_name", lambda: "Argon")
    monkeypatch.setattr(
        setup.wizard, "finish", lambda **keywords: finished.append(keywords)
    )
    answers = _NoAnswers()
    answers.is_https_enabled = True

    setup._setup(_SilentReporter(), [], answers)

    assert finished[0]["authority"] == {
        "url": "http://192.168.8.1:8080/api/hub/setting/https/authority",
        "file_name": "neutrino-argon-ca.crt",
        "fingerprint": hashlib.sha256(der).hexdigest(),
        "der": base64.b64encode(der).decode("ascii"),
    }
    lines = setup.wizard.authority_lines(finished[0]["authority"])
    assert lines[1].strip() == finished[0]["authority"]["url"]
    assert lines[2].startswith("  SHA-256 ")
    assert lines[2].count(":") == 31


def test_an_http_run_hands_over_no_authority(monkeypatch):
    finished: list = []
    monkeypatch.setattr(setup, "store_password", lambda password: None)
    monkeypatch.setattr(setup, "_panel_url", lambda: "http://192.168.8.1:8080")
    monkeypatch.setattr(setup, "_start_panel", lambda reporter: True)
    monkeypatch.setattr(setup, "_install_local_agent", lambda password, reporter: None)
    monkeypatch.setattr(setup, "_enrollment_link", lambda password: ("", ""))
    monkeypatch.setattr(
        setup.wizard, "finish", lambda **keywords: finished.append(keywords)
    )

    setup._setup(_SilentReporter(), [], _NoAnswers())

    assert finished[0]["authority"] is None
