"""What NetBird registers through the edition table, and its part of the page.

Pinned here: a binding keeps a NetBird object with its setup key and may
name no management URL, fqdn or address; the carried binary resolves where
each package puts it; the page inlines NetBird's part before its own script,
which names the engine, the way in and the row of About.
"""

from neutrino_client import bundled, edition
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


def test_the_table_gives_the_driver_and_the_object():
    assert edition.has_feature("netbird") is True
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


def test_the_page_inlines_the_part_before_its_own_script():
    document = page.control_page_html()
    part = page.gui_parts()

    assert "overlayTitles: { netbird: 'NetBird' }" in part
    assert "throughWays: ['netbird']" in part
    assert "{ name: 'NetBird', key: 'netbird', licence: 'BSD-3-Clause'," in part
    assert document.index(part) < document.index("const PARTS = window.NEUTRINO_PARTS")
