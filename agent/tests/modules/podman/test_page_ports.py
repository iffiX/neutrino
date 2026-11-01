"""The loopback port a hub container's page is published at, kept in its module's record."""

import json
import os
import stat

from neutrino_agent.constants import AGENT_PAGE_PORT_BASE
from neutrino_agent.modules.podman.page_ports import PodmanPagePortStore


def test_a_pick_passes_the_ports_every_module_keeps(tmp_path):
    (tmp_path / "cloudcli").mkdir()
    (tmp_path / "cloudcli" / "ann.json").write_text(
        json.dumps({"upstream_port": AGENT_PAGE_PORT_BASE + 1})
    )
    store = PodmanPagePortStore(directory=str(tmp_path))

    first = store.port_for("demo", "neutrino_demo")
    other = store.port_for("other", "neutrino_other")

    assert first >= AGENT_PAGE_PORT_BASE
    assert AGENT_PAGE_PORT_BASE + 1 not in (first, other)
    assert first != other


def test_a_pick_is_handed_the_state_root(tmp_path):
    seen: list = []

    def pick(root):
        seen.append(root)
        return 41000

    PodmanPagePortStore(directory=str(tmp_path), pick=pick).port_for("demo", "a")

    assert seen == [str(tmp_path)]


def test_a_port_the_system_accepts_stays_at_a_render(tmp_path):
    store = PodmanPagePortStore(
        directory=str(tmp_path), pick=lambda root: 41000, is_refused=lambda port: False
    )
    first = store.rendered_port_for("demo", "neutrino_demo")
    store._pick = lambda root: 42000

    assert store.rendered_port_for("demo", "neutrino_demo") == first == 41000
    assert store.refused_ports("demo") == []


def test_a_port_the_system_refuses_is_picked_again_at_a_render_and_kept(tmp_path):
    lines: list = []
    store = PodmanPagePortStore(
        directory=str(tmp_path),
        pick=lambda root: 41000,
        is_refused=lambda port: False,
        log=lines.append,
    )
    store.port_for("demo", "neutrino_demo")
    store._is_refused = {41000}.__contains__
    store._pick = lambda root: 42000

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
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda root: next(picks))

    first = store.port_for("demo", "neutrino_demo")
    again = PodmanPagePortStore(directory=str(tmp_path)).port_for(
        "demo", "neutrino_demo"
    )
    other = store.port_for("demo", "neutrino_demo_admin")

    assert (first, again, other) == (41000, 41000, 41001)
    assert store.ports("demo") == {"neutrino_demo": 41000, "neutrino_demo_admin": 41001}


def test_the_record_is_root_only_in_the_module_s_directory(tmp_path):
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda root: 41000)

    store.port_for("demo", "neutrino_demo")

    path = tmp_path / "demo" / "page_ports.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "demo").st_mode) == 0o700


def test_removing_a_module_forgets_its_ports(tmp_path):
    store = PodmanPagePortStore(directory=str(tmp_path), pick=lambda root: 41000)
    store.port_for("demo", "neutrino_demo")

    store.remove("demo")

    assert store.ports("demo") == {}
    assert not (tmp_path / "demo").exists()


def test_a_record_that_does_not_read_holds_no_port(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "page_ports.json").write_text('{"neutrino_demo": "x"}')

    assert PodmanPagePortStore(directory=str(tmp_path)).ports("demo") == {}
