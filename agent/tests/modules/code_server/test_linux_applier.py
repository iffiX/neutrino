"""code-server on Linux, with systemd and the account database faked.

What these pin: the template unit runs the release's launcher as
``User=%i`` on the account's socket with code-server's own login off; an
account the machine does not have, and one whose socket path is too long,
is refused before anything is written; no release is a failed download; a
new instance is enabled and restarted and a known one only kept up; the
run directory is the account's own; and an instance no longer named is
disabled and its run directory deleted.
"""

import os

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.config import CodeServerConfig
from neutrino_agent.modules.code_server.linux_applier import (
    CodeServerLinuxApplier,
    instance_unit,
    render_unit,
)
from neutrino_agent.modules.subprocess_run import CommandResult

CONFIG = CodeServerConfig.from_dict(
    {"instances": [{"account": "ann", "port": 8443, "secret": "s"}]}
)


class Machine:
    """systemctl, recorded."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        return CommandResult(list(command), 0, "", "")


def lookup(account):
    if account != "ann":
        raise KeyError(account)
    return 1001, 1002, "/home/ann"


@pytest.fixture
def machine():
    return Machine()


@pytest.fixture
def applier(tmp_path, machine):
    module_dir = tmp_path / "code_server"
    (module_dir / "release" / "bin").mkdir(parents=True)
    (module_dir / "release" / "bin" / "code-server").write_text("#!/bin/sh\n")
    (tmp_path / "systemd").mkdir()
    owners = []
    made = CodeServerLinuxApplier(
        module_dir=str(module_dir),
        record_dir=str(tmp_path / "records"),
        run=machine,
        lookup_account=lookup,
        chown=lambda path, uid, gid: owners.append((path, uid, gid)),
        systemd_dir=str(tmp_path / "systemd"),
    )
    made.owners = owners
    return made


def test_the_unit_runs_the_launcher_as_the_account_on_its_socket():
    unit = render_unit("/var/lib/neutrino/agent/code_server")

    assert "User=%i\n" in unit
    assert (
        "ExecStart=/var/lib/neutrino/agent/code_server/release/bin/code-server "
        "--socket /var/lib/neutrino/agent/code_server/run/%i/code_server.sock "
        "--auth none --socket-mode 600 --disable-telemetry --disable-update-check\n"
    ) in unit
    assert instance_unit("ann") == "neutrino_code_server@ann.service"


def test_a_new_instance_is_enabled_and_restarted_in_its_own_run_directory(
    applier, machine, tmp_path
):
    notes = applier.apply(CONFIG)

    assert ["systemctl", "daemon-reload"] in machine.calls
    assert machine.calls[-2:] == [
        ["systemctl", "enable", "neutrino_code_server@ann.service"],
        ["systemctl", "restart", "neutrino_code_server@ann.service"],
    ]
    run_dir = str(tmp_path / "code_server" / "run" / "ann")
    assert applier.owners == [(run_dir, 1001, 1002)]
    assert os.path.isdir(run_dir)
    assert notes == ["started code-server of ann"]
    assert applier.held_accounts() == ["ann"]


def test_a_known_instance_is_only_kept_up(applier, machine):
    applier.apply(CONFIG)
    machine.calls.clear()

    assert applier.apply(CONFIG) == []
    assert machine.calls == [
        ["systemctl", "enable", "--now", "neutrino_code_server@ann.service"]
    ]


def test_an_instance_no_longer_named_is_disabled_and_its_run_directory_deleted(
    applier, machine, tmp_path
):
    applier.apply(CONFIG)

    applier.apply(CodeServerConfig.from_dict({"instances": []}))

    assert [
        "systemctl",
        "disable",
        "--now",
        "neutrino_code_server@ann.service",
    ] in machine.calls
    assert applier.held_accounts() == []
    assert not os.path.exists(tmp_path / "code_server" / "run" / "ann")


@pytest.mark.parametrize(
    ("account", "code"), [("bob", "account_unknown"), ("a" * 64, "account_invalid")]
)
def test_an_account_that_cannot_run_is_refused_before_anything_is_written(
    applier, machine, tmp_path, account, code
):
    if code == "account_invalid":
        applier._lookup_account = lambda name: (1, 1, "/home/x")
    config = CodeServerConfig.from_dict(
        {"instances": [{"account": account, "port": 8443, "secret": "s"}]}
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(config)

    assert caught.value.code == code
    assert caught.value.params == {"account": account}
    assert machine.calls == []
    assert os.listdir(tmp_path / "systemd") == []


def test_no_release_is_a_failed_download(tmp_path, machine):
    applier = CodeServerLinuxApplier(
        module_dir=str(tmp_path / "empty"),
        record_dir=str(tmp_path / "records"),
        run=machine,
        lookup_account=lookup,
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG)

    assert caught.value.code == "code_server_download_failed"


def test_remove_disables_every_instance_and_deletes_the_template(
    applier, machine, tmp_path
):
    applier.apply(CONFIG)

    applier.remove()

    assert os.listdir(tmp_path / "systemd") == []
    assert applier.units() == []
