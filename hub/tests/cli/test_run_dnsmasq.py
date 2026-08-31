"""What `nhub run --only-dnsmasq` becomes.

The unit starts the hub, and the hub replaces itself with dnsmasq. What it
passes is the whole argument list dnsmasq gets: no configuration directory is
read, so a distribution's own /etc/dnsmasq.conf cannot contradict the file the
hub rendered.
"""

import pytest

from neutrino_hub.cli import run
from neutrino_hub.modules.router.constants import ROUTER_DNSMASQ_PATH


@pytest.fixture
def execed(monkeypatch):
    """Capture the exec instead of performing it."""
    calls = []
    monkeypatch.setattr(run.os, "execv", lambda path, args: calls.append((path, args)))
    monkeypatch.setattr(run.os.path, "isfile", lambda path: path == "/usr/bin/dnsmasq")
    return calls


def test_it_names_the_generated_file_and_reads_no_directory(execed, monkeypatch):
    monkeypatch.setattr(run.pwd, "getpwnam", _no_such_user)

    run._exec_dnsmasq()

    _, arguments = execed[0]
    assert f"--conf-file={ROUTER_DNSMASQ_PATH}" in arguments
    assert not [argument for argument in arguments if "conf-dir" in argument]


def test_it_finds_dnsmasq_where_the_family_put_it(execed, monkeypatch):
    """Debian and Fedora say sbin, Arch says bin."""
    monkeypatch.setattr(run.pwd, "getpwnam", _no_such_user)

    run._exec_dnsmasq()

    binary, arguments = execed[0]
    assert binary == "/usr/bin/dnsmasq"
    assert arguments[0] == "/usr/bin/dnsmasq"


def test_it_drops_privilege_to_the_account_the_package_made(execed, monkeypatch):
    monkeypatch.setattr(run.pwd, "getpwnam", lambda name: name)

    run._exec_dnsmasq()

    assert "--user=dnsmasq" in execed[0][1]


def test_it_starts_without_the_account_rather_than_failing(execed, monkeypatch):
    """A machine whose dnsmasq package made no user still gets DNS, on
    dnsmasq's own built-in default."""
    monkeypatch.setattr(run.pwd, "getpwnam", _no_such_user)

    run._exec_dnsmasq()

    assert not [argument for argument in execed[0][1] if argument.startswith("--user")]


def test_it_says_so_when_dnsmasq_is_not_installed(monkeypatch, capsys):
    monkeypatch.setattr(run.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(run.shutil, "which", lambda name: None)

    assert run._exec_dnsmasq() == 1
    assert "not installed" in capsys.readouterr().err


def _no_such_user(name):
    raise KeyError(name)
