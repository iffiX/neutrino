"""The panel's HTTP port in a file every local account reads.

What is pinned is that the file holds the port alone, readable by every
account, that the platform's permissions are set on it, and that a missing,
unreadable or garbled file reads as the default port.
"""

import os
import stat

import pytest

from neutrino_hub.web import panel_port
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT


def test_the_file_holds_the_port_alone_readable_by_every_account():
    panel_port.write_panel_port(80)

    path = panel_port.WEB_PANEL_PORT_PATH
    assert path.read_text() == "80\n"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    assert panel_port.read_panel_port() == 80


def test_the_platform_sets_the_file_readable_by_every_account(monkeypatch):
    opened: list = []

    class Platform:
        def make_readable_by_all(self, path):
            opened.append(path)

    monkeypatch.setattr(panel_port, "hub_platform", Platform)

    panel_port.write_panel_port(8090)

    assert opened == [panel_port.WEB_PANEL_PORT_PATH]


def test_a_missing_file_reads_as_the_default_port():
    assert panel_port.read_panel_port() == WEB_DEFAULT_LISTEN_PORT


@pytest.mark.parametrize("text", ["", "eighty\n", "{}"])
def test_a_garbled_file_reads_as_the_default_port(text):
    panel_port.WEB_PANEL_PORT_PATH.write_text(text)

    assert panel_port.read_panel_port() == WEB_DEFAULT_LISTEN_PORT


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file of mode 0")
def test_an_unreadable_file_reads_as_the_default_port():
    panel_port.write_panel_port(80)
    os.chmod(panel_port.WEB_PANEL_PORT_PATH, 0)

    assert panel_port.read_panel_port() == WEB_DEFAULT_LISTEN_PORT
