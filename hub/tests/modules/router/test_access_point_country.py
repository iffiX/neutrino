"""The access point's country: the regulatory step on apply, and the band.

A radio left in the world domain marks the 5 GHz channels "no IR", and
hostapd exits on them; the country the interface names is set on the system
before hostapd is handed it.
"""

import logging
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.router import wifi
from neutrino_hub.modules.router.hostapd_renderer import RouterHostapdRenderer

from tests.conftest import lan_entry, network_config


def interface(**settings):
    wifi_settings = {"ap_ssid": "neutrino", "ap_passphrase": "hunter2hunter2"}
    wifi_settings.update(settings)
    return network_config(
        lan_entry("wlp3s0", address="192.168.101.1", **wifi_settings)
    ).interface("wlp3s0")


def directives(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            values[key] = value
    return values


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """Every command publish runs, with the system domain reading ``00``."""
    commands = []

    def fake_run(command, **_):
        commands.append(command)
        is_reg_get = command[:3] == ["iw", "reg", "get"]
        return SimpleNamespace(
            is_success=True,
            stdout="global\ncountry 00: DFS-UNSET\n" if is_reg_get else "",
            stderr="",
            exit_code=0,
            command=command,
        )

    class FakeClient:
        def __init__(self, *, interface):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(wifi, "run", fake_run)
    monkeypatch.setattr(wifi, "RouterWifiClient", FakeClient)
    monkeypatch.setattr(
        wifi, "router_hostapd_config_path", lambda name: tmp_path / f"{name}.conf"
    )
    monkeypatch.setattr(
        wifi, "router_hostapd_address_path", lambda name: tmp_path / f"{name}.env"
    )
    monkeypatch.setattr(
        wifi,
        "write_generated",
        lambda path, text, mode: path.write_text(text, encoding="utf-8"),
    )
    return SimpleNamespace(commands=commands, config=tmp_path / "wlp3s0.conf")


def test_the_interface_s_country_is_set_on_the_system_before_hostapd_starts(machine):
    wifi.RouterWifiAccessPoint(interface="wlp3s0").publish(
        interface=interface(ap_band="a", ap_country_code="DE")
    )

    commands = [" ".join(command) for command in machine.commands]
    assert "iw reg set DE" in commands
    assert commands.index("iw reg set DE") < commands.index(
        "systemctl restart neutrino_hub_hostapd@wlp3s0.service"
    )
    config = directives(machine.config.read_text(encoding="utf-8"))
    assert config["country_code"] == "DE"
    assert config["ieee80211d"] == "1"
    assert config["hw_mode"] == "a"


def test_with_no_country_the_system_is_left_alone_and_the_radio_is_on_2_4_ghz(
    machine,
):
    """The system's own domain stays the fallback, and ``00`` is no country."""
    wifi.RouterWifiAccessPoint(interface="wlp3s0").publish(interface=interface())

    assert not any(command[:3] == ["iw", "reg", "set"] for command in machine.commands)
    config = directives(machine.config.read_text(encoding="utf-8"))
    assert "country_code" not in config
    assert config["hw_mode"] == "g"


def test_the_renderer_writes_the_country_it_is_given():
    config = directives(
        RouterHostapdRenderer(
            interface=interface(ap_band="a", ap_country_code="JP"),
            country_code="JP",
        ).render()
    )

    assert (config["hw_mode"], config["channel"]) == ("a", "36")
    assert (config["country_code"], config["ieee80211d"]) == ("JP", "1")


def test_an_old_5_ghz_configuration_with_no_country_publishes_on_2_4_ghz(caplog):
    with caplog.at_level(logging.WARNING):
        config = directives(
            RouterHostapdRenderer(interface=interface(ap_band="a")).render()
        )

    assert (config["hw_mode"], config["channel"]) == ("g", "6")
    assert "country_code" not in config
    assert "5 GHz needs a country code" in caplog.text
