"""The ports on loopback the agent takes for its listeners and instances.

What these pin: a port another program listens on is not free and one
nobody holds is; a port with a listener accepts a connection and one
without does not; a bind the system answers with a permission error is a
refused port, and a port another program listens on is not; a pick is the
first free port from the base up, past the ports taken; a base outside the
port range is refused; a pick that finds nothing free fails; and a page's port
is the first free one from 15000 up, past every port a module keeps and every
port picked before and not yet kept.
"""

import json
import socket

import pytest

from neutrino_agent.modules.shared import loopback_port as loopback_port_module
from neutrino_agent.constants import AGENT_PAGE_PORT_BASE
from neutrino_agent.modules.shared.loopback_port import (
    is_listening,
    is_port_free,
    is_port_refused,
    kept_page_ports,
    pick_page_port,
    pick_port,
)

# Where the lowest dynamic ports of any system begin, Linux's.
DYNAMIC_PORT_MIN = 32768


def test_a_port_another_program_listens_on_is_not_free():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert is_port_free(port) is False
    finally:
        holder.close()

    assert is_port_free(port) is True


def test_a_port_with_a_listener_accepts_a_connection_and_one_without_does_not():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert is_listening(port) is True
    finally:
        holder.close()

    assert is_listening(port) is False


class RefusedSocket:
    """A socket whose bind Windows answers as it does for a port it reserved."""

    def __init__(self, *arguments):
        pass

    def bind(self, address):
        raise PermissionError(13, "forbidden by its access permissions")

    def close(self):
        pass


def test_a_bind_the_system_refuses_reads_as_a_refused_port(monkeypatch):
    monkeypatch.setattr(loopback_port_module.socket, "socket", RefusedSocket)

    assert is_port_refused(64586) is True


def test_a_free_port_and_a_port_in_use_are_not_refused():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert is_port_refused(port) is False
    finally:
        holder.close()

    assert is_port_refused(port) is False


def test_a_pick_is_the_first_free_port_from_the_base_past_the_taken():
    held = {3001, 3003}

    port = pick_port(3001, taken=[3002], is_free=lambda port: port not in held)

    assert port == 3004


def test_a_base_outside_the_range_is_refused():
    with pytest.raises(ValueError):
        pick_port(0)


def test_a_pick_with_nothing_free_fails():
    with pytest.raises(OSError):
        pick_port(65530, is_free=lambda port: False)


def keep(root, module, name, held) -> None:
    """One file of one module's, as the module keeps it under the state root."""
    directory = root / module
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(json.dumps(held))


def test_a_page_port_is_free_from_the_base_up_below_the_dynamic_ports(tmp_path):
    port = pick_page_port(str(tmp_path))

    assert AGENT_PAGE_PORT_BASE <= port < DYNAMIC_PORT_MIN
    assert AGENT_PAGE_PORT_BASE == 15000
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_a_page_port_is_the_first_free_one_from_the_base(tmp_path):
    assert pick_page_port(str(tmp_path), is_free=lambda port: port != 15000) == 15001


def test_every_port_a_module_keeps_for_a_page_is_read(tmp_path):
    keep(tmp_path, "hermes_webui", "page_ports.json", {"neutrino_webui": 15000})
    keep(tmp_path, "hermes_webui", "hermes_webui.json", {"upstream_port": 15000})
    keep(tmp_path, "cloudcli", "ann.json", {"port": 3001, "upstream_port": 15001})
    keep(tmp_path, "codeg", "ann.json", {"port": 3101, "upstream_port": 51280})
    keep(tmp_path, "siyuan", "ann.json", {"port": 6810, "kernel_port": 53691})
    keep(tmp_path, "code_server", "ann.json", {"port": 8444})

    assert kept_page_ports(str(tmp_path)) == {15000, 15001, 51280, 53691}


def test_a_file_that_does_not_read_keeps_no_port(tmp_path):
    (tmp_path / "loose.json").write_text("{}")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "ann.json").write_text("not json")
    (tmp_path / "demo" / "list.json").write_text("[1]")
    (tmp_path / "demo" / ".record_x.json").write_text('{"upstream_port": 15000}')
    keep(tmp_path, "demo", "bob.json", {"upstream_port": "x"})
    keep(tmp_path, "other", "page_ports.json", {"neutrino_x": "y", "neutrino_y": True})

    assert kept_page_ports(str(tmp_path)) == set()
    assert kept_page_ports(str(tmp_path / "missing")) == set()


def test_a_pick_passes_the_ports_any_module_keeps(tmp_path):
    keep(tmp_path, "hermes_webui", "page_ports.json", {"neutrino_webui": 15000})
    keep(tmp_path, "cloudcli", "ann.json", {"upstream_port": 15001})

    assert pick_page_port(str(tmp_path), is_free=lambda port: True) == 15002


def test_a_pick_passes_a_port_picked_before_and_not_yet_kept(tmp_path):
    root = str(tmp_path)

    first = pick_page_port(root, is_free=lambda port: True)
    second = pick_page_port(root, is_free=lambda port: True)

    assert (first, second) == (15000, 15001)
