"""Installing the carried NetBird client, with systemd and the network faked.

The client travels inside the package, so provisioning a packaged box writes
a unit in front of a binary that is already there; a checkout has no package
to have staged one and fetches the pinned release instead.
"""

import hashlib
import io
import tarfile

import pytest

from neutrino_hub.modules.netbird import provisioner as module
from neutrino_hub.modules.netbird.constants import (
    NETBIRD_BINARY_NAME,
    NETBIRD_UNIT,
    NETBIRD_VENDOR_UNIT,
    NETBIRD_VERSION,
)
from neutrino_hub.modules.registry import MODULE_SPECS
from neutrino_hub.system.constants import SYSTEM_OPTIONAL_UNITS
from neutrino_hub.utils.constants import UTILS_DATA_DIR

PACKAGED_UNIT = (UTILS_DATA_DIR / "services" / NETBIRD_UNIT).read_text(encoding="utf-8")


class FakeResult:
    def __init__(self):
        self.stdout = ""
        self.stderr = ""
        self.exit_code = 0
        self.is_success = True


def a_box(
    tmp_path,
    monkeypatch,
    *,
    is_binary_present=True,
    is_vendor_installed=False,
    is_dev_root_set=False,
    tarball=None,
):
    """A machine of this test's own making, and the commands it is given.

    Args:
        tmp_path: The test's directory.
        monkeypatch: The fixture.
        is_binary_present: Whether the package already staged the client.
        is_vendor_installed: Whether the vendor's own unit is on the box.
        is_dev_root_set: Whether this is a development root.
        tarball: What a download serves, when one is expected.

    Returns:
        The provisioner, the command vectors it ran, the systemd directory
        and the binary's path.
    """
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    binary = tmp_path / "bin" / NETBIRD_BINARY_NAME
    binary.parent.mkdir()
    if is_binary_present:
        binary.write_bytes(b"client")
    if is_vendor_installed:
        (systemd / NETBIRD_VENDOR_UNIT).write_text("[Unit]\n", encoding="utf-8")

    ran = []

    def fake_run(command, **kwargs):
        ran.append(command)
        if command[0] == "curl" and tarball is not None:
            (tmp_path / "served").write_bytes(tarball)
            target = command[command.index("-o") + 1]
            (tmp_path / "served").replace(target)
        return FakeResult()

    monkeypatch.setattr(module, "SYSTEM_SYSTEMD_DIR", systemd)
    monkeypatch.setattr(module, "NETBIRD_BINARY_PATH", binary)
    monkeypatch.setattr(module, "NETBIRD_STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(module, "is_dev_root_set", lambda: is_dev_root_set)
    monkeypatch.setattr(module, "machine_architecture", lambda: "amd64")
    monkeypatch.setattr(module, "require_architecture", lambda *args: None)
    monkeypatch.setattr(module, "run", fake_run)
    return module.NetbirdProvisioner(), ran, systemd, binary


def a_release(payload=b"the client"):
    """A release tarball shaped like the vendor's, and its digest.

    Args:
        payload: What the binary inside it holds.

    Returns:
        The archive's bytes and their sha256.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo(NETBIRD_BINARY_NAME)
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    archive = buffer.getvalue()
    return archive, hashlib.sha256(archive).hexdigest()


def test_a_carried_client_is_never_downloaded_again(tmp_path, monkeypatch):
    """The package staged the binary; provisioning is the unit alone."""
    provisioner, ran, _, _ = a_box(tmp_path, monkeypatch)

    result = provisioner.provision()

    assert not [command for command in ran if command[0] == "curl"]
    assert result.message == f"netbird {NETBIRD_VERSION}"


def test_the_vendors_own_daemon_is_stood_down_before_ours_starts(tmp_path, monkeypatch):
    """Two clients share one state file and one socket, and the later one
    overwrites the other's record of what to revert."""
    provisioner, ran, systemd, _ = a_box(
        tmp_path, monkeypatch, is_vendor_installed=True
    )

    provisioner.provision()

    stand_down = ran.index(["systemctl", "disable", "--now", NETBIRD_VENDOR_UNIT])
    start = ran.index(["systemctl", "enable", "--now", NETBIRD_UNIT])
    assert stand_down < start
    # The vendor's unit file is its package's, not this hub's to delete.
    assert (systemd / NETBIRD_VENDOR_UNIT).is_file()


def test_a_box_without_the_vendors_package_is_asked_nothing_about_it(
    tmp_path, monkeypatch
):
    provisioner, ran, _, _ = a_box(tmp_path, monkeypatch)

    provisioner.provision()

    assert ["systemctl", "disable", "--now", NETBIRD_VENDOR_UNIT] not in ran


def test_the_hubs_own_unit_is_written_and_enabled(tmp_path, monkeypatch):
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch)

    provisioner.provision()

    assert (systemd / NETBIRD_UNIT).read_text(encoding="utf-8") == PACKAGED_UNIT
    assert ["systemctl", "daemon-reload"] in ran
    assert ran[-1] == ["systemctl", "enable", "--now", NETBIRD_UNIT]


def test_a_unit_already_current_is_not_rewritten(tmp_path, monkeypatch):
    """Provisioning twice is provisioning once; the second call finds its work
    already done."""
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch)
    (systemd / NETBIRD_UNIT).write_text(PACKAGED_UNIT, encoding="utf-8")

    result = provisioner.provision()

    assert result.is_changed is False
    assert result.message == "already provisioned"
    assert ["systemctl", "daemon-reload"] not in ran


def test_a_development_root_installs_no_unit(tmp_path, monkeypatch):
    """A development root runs the panel in the foreground and owns no
    systemd."""
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch, is_dev_root_set=True)

    provisioner.provision()

    assert not list(systemd.iterdir())
    assert ran == []


def test_a_checkout_fetches_the_pinned_release(tmp_path, monkeypatch):
    """No package staged a binary, so the release the constants pin is what
    lands — and only the client comes out of it."""
    archive, digest = a_release()
    provisioner, ran, _, binary = a_box(
        tmp_path, monkeypatch, is_binary_present=False, tarball=archive
    )
    monkeypatch.setattr(module, "NETBIRD_SHA256", {"amd64": digest})

    result = provisioner.provision()

    assert ran[0][0] == "curl"
    assert NETBIRD_VERSION in ran[0][-1]
    assert binary.read_bytes() == b"the client"
    assert binary.stat().st_mode & 0o777 == 0o755
    assert result.is_changed is True


def test_a_download_that_is_not_what_was_pinned_is_refused(tmp_path, monkeypatch):
    """A binary nobody vouched for is not installed and then checked."""
    archive, _ = a_release()
    provisioner, _, _, binary = a_box(
        tmp_path, monkeypatch, is_binary_present=False, tarball=archive
    )
    monkeypatch.setattr(module, "NETBIRD_SHA256", {"amd64": "0" * 64})

    with pytest.raises(ValueError):
        provisioner.provision()

    assert not binary.exists()


def test_deprovision_leaves_the_binary_the_package_installed(tmp_path, monkeypatch):
    """The client is a file the hub's package owns; its package manager takes
    it away, and only on an uninstall."""
    provisioner, ran, systemd, binary = a_box(tmp_path, monkeypatch)
    (systemd / NETBIRD_UNIT).write_text(PACKAGED_UNIT, encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "state.json").write_text("{}")

    result = provisioner.deprovision()

    assert binary.is_file()
    assert not (systemd / NETBIRD_UNIT).exists()
    assert ["systemctl", "disable", "--now", NETBIRD_UNIT] in ran
    assert (tmp_path / "state" / "state.json").is_file()
    assert result.message == "removed; identity kept"


def test_deprovision_deletes_the_peer_identity_only_when_asked(tmp_path, monkeypatch):
    provisioner, _, _, binary = a_box(tmp_path, monkeypatch)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "state.json").write_text("{}")

    result = provisioner.deprovision(is_data_kept=False)

    assert not (tmp_path / "state").exists()
    assert binary.is_file()
    assert result.message == "removed, identity deleted"


def test_every_layer_names_the_same_unit():
    """``system/`` spells the unit out rather than importing a module for it,
    so the two are pinned against each other here."""
    assert SYSTEM_OPTIONAL_UNITS["netbird"] == NETBIRD_UNIT
    assert MODULE_SPECS["netbird"].unit == NETBIRD_UNIT


def test_the_shipped_unit_runs_the_client_the_package_carries():
    """The unit is not a template, so the path in it is a second copy of
    ``NETBIRD_BINARY_PATH`` and has to keep agreeing with it."""
    assert f"ExecStart={module.NETBIRD_BINARY_PATH} service run" in PACKAGED_UNIT
    assert "@PYTHON@" not in PACKAGED_UNIT
