"""``nclient ssh``: list, open, config and proxy against a scripted client.

A machine's host is the machine part of its apps' local names, ``.nt``
after it in ssh's eyes, and ``<machine>.<hub>`` where two hubs hold a
machine of one slug; its accounts come in the hub's order, the default
first. ``open`` runs the system's ssh with ``-F`` the client's file;
``config install`` and ``uninstall`` are the Settings switch; ``proxy``
carries stdin up and the stream down, exits 0 when it ends and 1 for a
refusal, and writes nothing but the stream to stdout.
"""

import io

import pytest

from neutrino_client.cli import names, ssh, wording

CONFIG = {"path": "/home/alice/.ssh/neutrino_config", "text": "Host lab-gpu.nt\n"}


@pytest.fixture
def config(running):
    running.answers["/api/ssh/config"] = lambda body: (200, dict(CONFIG))
    return running


def test_list_prints_each_machine_and_its_accounts_default_first(running, capsys):
    assert ssh.main_list() == 0
    assert capsys.readouterr().out.strip() == "lab-gpu  iffi lab"


def test_two_hubs_holding_one_machine_slug_name_each_by_its_hub(running):
    running.state["apps"].append(
        {
            "hub_id": "h2",
            "id": "ssh_server_d8",
            "title": "SSH",
            "device_id": "d8",
            "device_name": "lab-gpu",
            "local_name": "ssh.lab-gpu.localhost",
        }
    )
    running.state["services"].append(
        {
            "hub_id": "h2",
            "id": "ssh_server_d8_ci",
            "type": "ssh",
            "app_id": "ssh_server_d8",
            "name": "ci",
            "device_id": "d8",
            "device_name": "lab-gpu",
            "payload": {"account": "ci"},
        }
    )

    hosts = [row["host"] for row in names.ssh_hosts(running.state)]

    assert hosts == ["lab-gpu.home", "lab-gpu.office"]


def test_open_runs_ssh_against_the_clients_file(config):
    ran = []

    assert ssh.main_open("lab-gpu", [], run=lambda argv: ran.append(argv) or 0) == 0
    assert ran[0][1:] == [
        "-F",
        CONFIG["path"],
        "iffi@lab-gpu.nt",
    ]


def test_open_with_a_command_runs_it_and_returns_its_code(config):
    ran = []

    status = ssh.main_open(
        "lab@lab-gpu.nt", ["nvidia-smi", "-L"], run=lambda argv: ran.append(argv) or 4
    )

    assert status == 4
    assert ran[0][-3:] == ["lab@lab-gpu.nt", "nvidia-smi", "-L"]


def test_an_account_the_machine_does_not_enable_prints_its_accounts(config, capsys):
    assert ssh.main_open("root@lab-gpu", [], run=_never) == 1
    assert capsys.readouterr().err.strip() == (
        "no account named root; there are: iffi, lab"
    )


def test_a_machine_with_no_ssh_prints_the_ones_there_are(config, capsys):
    assert ssh.main_open("build", [], run=_never) == 1
    assert capsys.readouterr().err.strip() == (
        "no machine named build; there are: lab-gpu"
    )


def test_config_show_prints_the_path_and_the_text(config, capsys):
    assert ssh.main_config_show() == 0
    assert capsys.readouterr().out == CONFIG["path"] + "\n" + CONFIG["text"]


def test_config_show_of_a_file_not_written_says_so(running, capsys):
    running.answers["/api/ssh/config"] = lambda body: (
        200,
        {"path": CONFIG["path"], "text": ""},
    )

    assert ssh.main_config_show() == 0
    assert "is not written yet" in capsys.readouterr().out


@pytest.mark.parametrize("is_installed", [True, False])
def test_config_install_and_uninstall_are_the_settings_switch(running, is_installed):
    assert ssh.main_config_install(is_installed=is_installed) == 0
    assert running.posts("/api/settings/set") == [
        {"is_ssh_include_enabled": is_installed}
    ]


def test_proxy_carries_stdin_up_and_the_stream_down(running):
    running.output = [b"SSH-2.0-neutrino\r\n", b"rest"]
    out = io.BytesIO()

    status = ssh.main_proxy(
        "lab@lab-gpu.nt", stdin=io.BytesIO(b"SSH-2.0-OpenSSH\r\n"), stdout=out
    )

    assert status == 0
    assert out.getvalue() == b"SSH-2.0-neutrino\r\nrest"
    assert running.requests[1] == (
        "UPGRADE",
        "/api/ssh/proxy",
        {"hub_id": "h1", "entry_id": "ssh_server_d1_lab"},
    )
    assert b"".join(running.kept["/api/ssh/proxy"].sent) == b"SSH-2.0-OpenSSH\r\n"


def test_proxy_with_no_account_takes_the_first(running):
    assert ssh.main_proxy("lab-gpu", stdin=io.BytesIO(), stdout=io.BytesIO()) == 0
    assert running.requests[1][2]["entry_id"] == "ssh_server_d1_iffi"


def test_proxy_refused_at_the_open_is_exit_1_on_stderr_alone(running, capsys):
    running.upgrades["/api/ssh/proxy"] = (
        403,
        {"code": "permission_denied", "params": {"kind": "ssh"}},
    )
    out = io.BytesIO()

    assert ssh.main_proxy("lab-gpu", stdin=io.BytesIO(), stdout=out) == 1
    assert out.getvalue() == b""
    assert capsys.readouterr().err.strip() == (
        "the hub gives this client no ssh permission"
    )


def test_proxy_whose_stream_the_hub_closed_with_a_code_is_exit_1(running, capsys):
    running.result = {"code": "agent_offline", "params": {"device": "d1"}}

    assert ssh.main_proxy("lab-gpu", stdin=io.BytesIO(), stdout=io.BytesIO()) == 1
    assert capsys.readouterr().err.strip() == "lab-gpu is offline"


def test_proxy_with_no_running_client_is_exit_1(running, capsys):
    running.is_running = False

    assert ssh.main_proxy("lab-gpu", stdin=io.BytesIO(), stdout=io.BytesIO()) == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


@pytest.mark.parametrize(
    "call",
    [
        lambda: ssh.main_list(),
        lambda: ssh.main_open("lab-gpu", [], run=_never),
        lambda: ssh.main_config_show(),
        lambda: ssh.main_config_install(is_installed=True),
    ],
)
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


def _never(argv):
    raise AssertionError("ssh ran")
