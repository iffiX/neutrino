"""What NetBird adds beside EasyTier, and its words on the page.

Pinned here: a binding keeps a NetBird object with its setup key and may
name no management URL, fqdn or address; the carried binary resolves where
each package puts it; the page names the engine, the way in and the row of
About.
"""

from neutrino_client import bundled
from neutrino_client.control import page
from neutrino_client.core import enrollment
from neutrino_client.core.overlay import overlay_engines
from neutrino_client.netbird.constants import NETBIRD_BUNDLED_PATHS
from neutrino_client.netbird.driver import OverlayNetbirdDriver

NETBIRD = {
    "provider": "netbird",
    "setup_key": "K",  # scan: allow
    "management_url": "",
    "fqdn": "",
    "hub_address": "",
}


def test_netbird_is_the_driver_beside_easytier():
    assert overlay_engines() == {"netbird": OverlayNetbirdDriver}


def test_a_binding_keeps_a_netbird_object_that_names_only_its_key():
    assert enrollment.clean_overlay(dict(NETBIRD, mode="")) == NETBIRD
    assert enrollment.clean_overlay(dict(NETBIRD, setup_key=" ")) is None


def test_the_carried_binary_resolves_under_the_linux_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(bundled, "CLIENT_INSTALL_PREFIX_LINUX", str(tmp_path))
    monkeypatch.setattr(bundled.os, "name", "posix")
    monkeypatch.setattr(bundled.sys, "platform", "linux")
    binary = tmp_path / NETBIRD_BUNDLED_PATHS["linux"]["netbird"]
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    assert bundled.bundled_path("netbird") == str(binary)
    assert NETBIRD_BUNDLED_PATHS["windows"]["netbird"] == "bin\\netbird.exe"


def test_the_page_names_netbird_itself():
    script = page.gui_asset("app.js")

    assert "const OVERLAY_TITLES = { netbird: 'NetBird', easytier: 'EasyTier' };" in (
        script
    )
    assert (
        "const THROUGH_WAYS = ["
        "'lan', 'netbird', 'easytier', 'ssh_relay', 'direct', 'sakurafrp', 'openfrp'];"
        in script
    )
    assert "{ name: 'NetBird', key: 'netbird', licence: 'BSD-3-Clause'," in script
