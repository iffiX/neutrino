"""Instances on Linux, with systemd and the account database faked.

What these pin: the template unit runs the program as ``User=%i``, with an
environment file, a working directory and a umask only when the service
names them; a discarded output goes to systemd's null; a secret
environment is root-only and quoted, a plain one readable and bare; the
template is loaded once when it changed; a changed
instance is started again and an unchanged one only kept up; a stop keeps
the unit enabled; a remove disables it and deletes what it ran from; and
the states are read off ``systemctl is-active``.
"""

import os
import stat

import pytest

from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service.linux import (
    render_environment,
    render_unit,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult


class Systemd:
    """systemctl, recorded; every unit the test names active reads active."""

    def __init__(self):
        self.calls: list = []
        self.active: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "is-active"]:
            word = "active" if command[2] in self.active else "inactive"
            return CommandResult(list(command), 0, word + "\n", "")
        return CommandResult(list(command), 0, "", "")


def service_with(**changes) -> AccountService:
    fields = {
        "name": "demo",
        "title": "Demo",
        "account": "ann",
        "command": ("/opt/demo/bin/demo", "--port", "${DEMO_PORT}"),
        "environment": {"DEMO_PORT": "8000"},
    }
    fields.update(changes)
    return AccountService(**fields)


@pytest.fixture
def systemd():
    return Systemd()


@pytest.fixture
def owners():
    return []


@pytest.fixture
def machine(systemd, tmp_path, owners):
    (tmp_path / "systemd").mkdir()

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return AccountEntry(1000, 1001, "/home/ann")

    return ServiceMachine(
        os_name="linux",
        module_dir=str(tmp_path / "state" / "demo"),
        record_dir=str(tmp_path / "config" / "demo"),
        lookup_account=lookup,
        run=systemd,
        chown=lambda path, uid, gid: owners.append((os.path.basename(path), uid, gid)),
        systemd_dir=str(tmp_path / "systemd"),
    )


def test_the_template_names_the_environment_file_and_the_working_directory():
    template = service_with(account="%i", working_directory="~", umask="077")

    unit = render_unit(template, environment_dir="/etc/neutrino/agent/demo")

    assert unit.split("\n")[5:12] == [
        "[Service]",
        "Type=simple",
        "User=%i",
        "EnvironmentFile=/etc/neutrino/agent/demo/%i.env",
        "WorkingDirectory=~",
        "UMask=077",
        "ExecStart=/opt/demo/bin/demo --port ${DEMO_PORT}",
    ]
    assert unit.startswith("[Unit]\nDescription=Demo for %i\n")
    assert unit.endswith("\n[Install]\nWantedBy=multi-user.target\n")


def test_a_template_without_an_environment_names_no_file():
    unit = render_unit(
        service_with(account="%i", environment={}), environment_dir="/etc/x"
    )

    assert "EnvironmentFile" not in unit
    assert "WorkingDirectory" not in unit
    assert "UMask" not in unit


def test_a_discarded_output_goes_to_systemds_null():
    discarded = render_unit(
        service_with(account="%i", umask="077", is_output_discarded=True),
        environment_dir="/etc/x",
    )
    kept = render_unit(service_with(account="%i"), environment_dir="/etc/x")

    assert "UMask=077\nStandardOutput=null\nStandardError=null\nExecStart=" in (
        discarded
    )
    assert "StandardOutput" not in kept and "StandardError" not in kept


def test_an_environment_file_is_bare_or_quoted():
    assert render_environment({"A": "1", "B": "x y"}, is_quoted=False) == (
        "A=1\nB=x y\n"
    )
    assert render_environment({"A": 'x "y" \\z'}, is_quoted=True) == (
        'A="x \\"y\\" \\\\z"\n'
    )


def test_the_template_is_written_and_loaded_once(machine, systemd, tmp_path):
    template = service_with(account="%i")

    assert account_service.define(template, machine) is True
    assert account_service.define(template, machine) is False

    path = tmp_path / "systemd" / "neutrino_demo@.service"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    assert "EnvironmentFile=" + str(tmp_path / "config" / "demo") + "/%i.env" in (
        path.read_text()
    )
    assert systemd.calls == [["systemctl", "daemon-reload"]]


def test_a_plain_environment_goes_where_the_service_says_readable(
    owners, machine, systemd, tmp_path
):
    environment_dir = str(tmp_path / "state" / "demo" / "tokens")
    token = os.path.join(environment_dir, "ann.token")
    service = service_with(environment_dir=environment_dir, files=((token, "t-ann"),))

    assert account_service.write(service, machine) is True
    assert account_service.write(service, machine) is False

    environment = os.path.join(environment_dir, "ann.env")
    assert open(environment).read() == "DEMO_PORT=8000\n"
    assert stat.S_IMODE(os.stat(environment).st_mode) == 0o644
    assert stat.S_IMODE(os.stat(environment_dir).st_mode) == 0o755
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert owners[0] == ("ann.token", 1000, 1001)


def test_a_secret_environment_is_root_only_beside_the_records(machine, tmp_path):
    service = service_with(is_environment_secret=True)

    account_service.write(service, machine)

    environment = tmp_path / "config" / "demo" / "ann.env"
    assert environment.read_text() == 'DEMO_PORT="8000"\n'
    assert stat.S_IMODE(os.stat(environment).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(environment.parent).st_mode) == 0o700


def test_a_service_without_an_environment_writes_no_file(machine, tmp_path):
    service = service_with(environment={}, directories=(str(tmp_path / "run"),))

    assert account_service.write(service, machine) is False
    assert not (tmp_path / "config").exists()
    assert stat.S_IMODE(os.stat(tmp_path / "run").st_mode) == 0o700


def test_an_account_the_machine_lacks_is_a_key_error(machine):
    with pytest.raises(KeyError):
        account_service.write(service_with(account="ghost"), machine)


def test_a_changed_instance_is_started_again_and_an_unchanged_one_kept_up(
    machine, systemd
):
    service = service_with()

    account_service.start(service, machine, is_restart=True)
    account_service.start(service, machine, is_restart=False)

    assert systemd.calls == [
        ["systemctl", "enable", "neutrino_demo@ann.service"],
        ["systemctl", "restart", "neutrino_demo@ann.service"],
        ["systemctl", "enable", "--now", "neutrino_demo@ann.service"],
    ]


def test_a_stop_disables_the_unit_and_a_remove_takes_everything(
    machine, systemd, tmp_path
):
    token = str(tmp_path / "tokens" / "ann.token")
    service = service_with(
        files=((token, "t"),), directories=(str(tmp_path / "run" / "ann"),)
    )
    account_service.write(service, machine)
    systemd.calls.clear()

    account_service.stop(service, machine)
    account_service.remove(service, machine)

    # A stopped instance stays stopped across a reboot.
    assert systemd.calls == [
        ["systemctl", "disable", "--now", "neutrino_demo@ann.service"],
        ["systemctl", "disable", "--now", "neutrino_demo@ann.service"],
    ]
    assert not os.path.exists(tmp_path / "config" / "demo" / "ann.env")
    assert not os.path.exists(token)
    assert not os.path.exists(tmp_path / "run" / "ann")


def test_the_states_are_read_off_each_unit(machine, systemd):
    systemd.active.add("neutrino_demo@ann.service")
    services = [service_with(), service_with(account="bob")]

    assert account_service.states(services, machine) == {
        "ann": {"is_running": True, "code": ""},
        "bob": {"is_running": False, "code": ""},
    }
    assert account_service.units(services, machine) == [
        "neutrino_demo@ann.service",
        "neutrino_demo@bob.service",
    ]


def test_a_systemd_that_cannot_be_asked_reads_as_not_running(machine):
    def refusing(command, **kwargs):
        raise OSError("no systemd")

    machine = ServiceMachine(
        os_name="linux",
        module_dir=machine.module_dir,
        record_dir=machine.record_dir,
        lookup_account=machine.lookup_account,
        run=refusing,
    )

    assert account_service.states([service_with()], machine) == {
        "ann": {"is_running": False, "code": ""}
    }


def test_forget_deletes_the_template_and_tells_systemd(machine, systemd, tmp_path):
    account_service.define(service_with(account="%i"), machine)
    systemd.calls.clear()

    account_service.forget("demo", machine)

    assert os.listdir(tmp_path / "systemd") == []
    assert systemd.calls == [["systemctl", "daemon-reload"]]
