"""Installing the rendered dnsmasq configuration.

A restart empties dnsmasq's cache, and every apply used to order one. The rule
here is that the file and the unit together decide: the same text over a
running dnsmasq is nothing to do, and the same text over a dead one is a
restart, because the file on disk cannot bring a stopped service back.
"""

import subprocess

import pytest

from neutrino_hub.modules.router import routes


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A dnsmasq whose file is in tmp_path, recording what was run.

    Returns the generated path, the commands that ran, and the unit state the
    next reading answers with, which a test may replace.
    """
    path = tmp_path / "dnsmasq_neutrino.conf"
    commands: list = []
    state = {"value": "active"}

    monkeypatch.setattr(routes, "ROUTER_DNSMASQ_PATH", path)
    monkeypatch.setattr(routes, "unit_state", lambda unit: state["value"])
    monkeypatch.setattr(
        routes, "run", lambda command, **keywords: commands.append(command)
    )
    monkeypatch.setattr(
        routes,
        "write_generated",
        lambda destination, text: destination.write_text(text, encoding="utf-8"),
    )
    return path, commands, state


def test_the_same_text_over_a_running_dnsmasq_restarts_nothing(installed):
    """The cache holds a thousand names, and a cold lookup through the proxy
    costs ten times what a cached one does."""
    path, commands, _ = installed
    path.write_text("interface=enp1s0\n", encoding="utf-8")

    assert routes.install_dnsmasq("interface=enp1s0\n") is False
    assert commands == []


def test_the_same_text_over_a_dead_dnsmasq_restarts_it(installed):
    """The file on disk already matches, so without reading the unit no apply
    would ever start dnsmasq again."""
    path, commands, state = installed
    path.write_text("interface=enp1s0\n", encoding="utf-8")
    state["value"] = "failed"

    assert routes.install_dnsmasq("interface=enp1s0\n") is True
    assert commands == [["systemctl", "restart", routes.DNSMASQ_SERVICE_NAME]]


def test_changed_text_is_written_and_restarted(installed):
    path, commands, _ = installed
    path.write_text("interface=enp1s0\n", encoding="utf-8")

    assert routes.install_dnsmasq("interface=wlp3s0\n") is True
    assert path.read_text(encoding="utf-8") == "interface=wlp3s0\n"
    assert commands == [["systemctl", "restart", routes.DNSMASQ_SERVICE_NAME]]


def test_a_missing_file_is_written_and_restarted(installed):
    path, commands, _ = installed

    assert routes.install_dnsmasq("interface=enp1s0\n") is True
    assert path.read_text(encoding="utf-8") == "interface=enp1s0\n"
    assert commands == [["systemctl", "restart", routes.DNSMASQ_SERVICE_NAME]]


def test_a_refused_restart_reaches_the_caller(installed, monkeypatch):
    """The apply says what failed; it does not report a dnsmasq it did not get."""

    def refuse(command, **keywords):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(routes, "run", refuse)

    with pytest.raises(subprocess.CalledProcessError):
        routes.install_dnsmasq("interface=enp1s0\n")
