"""What every platform shares: the lock on a Unix file, the command that
runs ``nhub`` itself, and the refusals a system class must answer."""

import os
import sys

import pytest

from neutrino_hub.platforms import base
from neutrino_hub.platforms.base import HubPlatform


def test_the_lock_is_held_once(tmp_path):
    path = tmp_path / "router.lock"
    first = os.open(path, os.O_RDWR | os.O_CREAT)
    second = os.open(path, os.O_RDWR)
    try:
        platform = HubPlatform()
        assert platform.try_lock(first)
        assert not platform.try_lock(second)
        platform.unlock(first)
        assert platform.try_lock(second)
    finally:
        os.close(first)
        os.close(second)


def test_a_checkout_runs_nhub_through_its_interpreter():
    assert HubPlatform().hub_command("apply", "--skip-apply") == [
        sys.executable,
        "-m",
        "neutrino_hub.cli.entry",
        "apply",
        "--skip-apply",
    ]


def test_the_compiled_binary_runs_itself(monkeypatch):
    monkeypatch.setattr(base, "is_compiled", lambda: True)

    assert HubPlatform().hub_command("apply") == [sys.executable, "apply"]


@pytest.mark.parametrize(
    "verb", ["service_state", "start_service", "stop_service", "restart_service"]
)
def test_the_one_service_is_not_the_bases_to_drive(verb):
    with pytest.raises(NotImplementedError):
        getattr(HubPlatform(), verb)()


def test_no_controller_and_no_browser_without_a_system_class():
    with pytest.raises(NotImplementedError):
        HubPlatform().process_controller()
    assert not HubPlatform().open_browser("http://127.0.0.1/")


# --- the system's own resolvers -----------------------------------------------


def test_resolv_conf_names_its_resolvers_in_order_once():
    text = (
        "# a comment\n"
        "search example.net\n"
        "nameserver 192.168.1.1\n"
        "nameserver 127.0.0.53\n"
        "nameserver fe80::1%eth0\n"
        "nameserver 2001:db8::53\n"
        "nameserver 192.168.1.1\n"
        "nameserver\n"
        "options edns0\n"
    )

    assert base.parse_resolv_conf(text) == ["192.168.1.1", "2001:db8::53"]


def test_resolveds_upstream_list_comes_before_its_stub(monkeypatch, tmp_path):
    upstreams = tmp_path / "resolve.conf"
    stub = tmp_path / "resolv.conf"
    upstreams.write_text("nameserver 192.0.2.53\n")
    stub.write_text("nameserver 127.0.0.53\n")
    monkeypatch.setattr(base, "PLATFORM_RESOLVER_FILES", (str(upstreams), str(stub)))

    assert HubPlatform().system_resolvers() == ["192.0.2.53"]


def test_a_stub_alone_and_no_file_both_name_none(monkeypatch, tmp_path):
    stub = tmp_path / "resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    monkeypatch.setattr(
        base, "PLATFORM_RESOLVER_FILES", (str(tmp_path / "missing"), str(stub))
    )

    assert HubPlatform().system_resolvers() == []
