"""The loopback port a hub container's page is published at, kept in its module's record."""

import os
import socket
import stat

from neutrino_agent.modules.podman.constants import PODMAN_PAGE_PORT_BASE
from neutrino_agent.modules.podman.page_ports import (
    PodmanPagePortStore,
    free_loopback_port,
)

# Where the lowest dynamic ports of any system begin, Linux's.
DYNAMIC_PORT_MIN = 32768


def test_a_free_port_is_one_nothing_listens_on_below_the_dynamic_ports():
    port = free_loopback_port()

    assert PODMAN_PAGE_PORT_BASE <= port < DYNAMIC_PORT_MIN
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_a_free_port_is_none_of_the_ports_taken():
    first = free_loopback_port()

    assert free_loopback_port(taken=[first]) != first


def test_a_pick_passes_the_ports_every_module_keeps(tmp_path):
    seen: list = []
    picks = iter([41000, 41001])

    def pick(taken):
        seen.append(set(taken))
        return next(picks)

    store = PodmanPagePortStore(directory=str(tmp_path), pick=pick)

    store.port_for("demo", "neutrino_demo")
    store.port_for("other", "neutrino_other")

    assert seen == [set(), {41000}]


def test_a_port_the_system_accepts_stays_at_a_render(tmp_path):
    store = PodmanPagePortStore(
        directory=str(tmp_path), pick=lambda taken: 41000, is_refused=lambda port: False
    )
    first = store.rendered_port_for("demo", "neutrino_demo")
    store._pick = lambda taken: 42000

    assert store.rendered_port_for("demo", "neutrino_demo") == first == 41000
    assert store.refused_ports("demo") == []


def test_a_port_the_system_refuses_is_picked_again_at_a_render_and_kept(tmp_path):
    lines: list = []
    store = PodmanPagePortStore(
        directory=str(tmp_path),
        pick=lambda taken: 41000,
        is_refused=lambda port: False,
        log=lines.append,
    )
    store.port_for("demo", "neutrino_demo")
    store._is_refused = {41000}.__contains__
    store._pick = lambda taken: 42000

    assert store.refused_ports("demo") == [41000]
    assert store.port_for("demo", "neutrino_demo") == 41000
    assert store.rendered_port_for("demo", "neutrino_demo") == 42000
    assert store.port_for("demo", "neutrino_demo") == 42000
    assert store.refused_ports("demo") == []
    assert lines == [
        "podman: the system refuses port 41000 of neutrino_demo, published at 42000 now"
    ]


def test_a_port_is_picked_once_per_container_and_kept(tmp_path):
    picks = iter([41000, 41001])
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda taken: next(picks))

    first = store.port_for("demo", "neutrino_demo")
    again = PodmanPagePortStore(directory=str(tmp_path)).port_for(
        "demo", "neutrino_demo"
    )
    other = store.port_for("demo", "neutrino_demo_admin")

    assert (first, again, other) == (41000, 41000, 41001)
    assert store.ports("demo") == {"neutrino_demo": 41000, "neutrino_demo_admin": 41001}


def test_the_record_is_root_only_in_the_module_s_directory(tmp_path):
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda taken: 41000)

    store.port_for("demo", "neutrino_demo")

    path = tmp_path / "demo" / "page_ports.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "demo").st_mode) == 0o700


def test_removing_a_module_forgets_its_ports(tmp_path):
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda taken: 41000)
    store.port_for("demo", "neutrino_demo")

    store.remove("demo")

    assert store.ports("demo") == {}
    assert not (tmp_path / "demo").exists()


def test_a_record_that_does_not_read_holds_no_port(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "page_ports.json").write_text('{"neutrino_demo": "x"}')

    assert PodmanPagePortStore(directory=str(tmp_path)).ports("demo") == {}
