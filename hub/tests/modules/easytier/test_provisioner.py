"""Installing the carried EasyTier engine, with systemd and the network faked.

The engine travels inside the package as two binaries, so provisioning a
packaged box writes a unit in front of files that are already there; a
checkout has no package to have staged them and fetches the pinned release
instead. The unit is enabled and not started: there is nothing to run on until
a network is written.
"""

import hashlib
import io
import zipfile

import pytest

from neutrino_hub.modules.easytier import provisioner as module
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_CLI_NAME,
    EASYTIER_CORE_NAME,
    EASYTIER_UNIT,
    EASYTIER_VERSION,
)
from neutrino_hub.modules.registry import MODULE_SPECS
from neutrino_hub.system.constants import SYSTEM_OPTIONAL_UNITS
from neutrino_hub.utils.constants import UTILS_DATA_DIR

PACKAGED_UNIT = (UTILS_DATA_DIR / "services" / EASYTIER_UNIT).read_text(
    encoding="utf-8"
)


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
    is_engine_present=True,
    is_dev_root_set=False,
    archive=None,
):
    """A machine of this test's own making, and the commands it is given.

    Args:
        tmp_path: The test's directory.
        monkeypatch: The fixture.
        is_engine_present: Whether the package already staged the binaries.
        is_dev_root_set: Whether this is a development root.
        archive: What a download serves, when one is expected.

    Returns:
        The provisioner, the command vectors it ran, the systemd directory
        and the two binary paths.
    """
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    core = binaries / EASYTIER_CORE_NAME
    cli = binaries / EASYTIER_CLI_NAME
    if is_engine_present:
        core.write_bytes(b"engine")
        cli.write_bytes(b"cli")

    ran = []

    def fake_run(command, **kwargs):
        ran.append(command)
        if command[0] == "curl" and archive is not None:
            target = command[command.index("-o") + 1]
            (tmp_path / "served").write_bytes(archive)
            (tmp_path / "served").replace(target)
        return FakeResult()

    monkeypatch.setattr(module, "SYSTEM_SYSTEMD_DIR", systemd)
    monkeypatch.setattr(module, "EASYTIER_CORE_PATH", core)
    monkeypatch.setattr(module, "EASYTIER_CLI_PATH", cli)
    monkeypatch.setattr(module, "is_dev_root_set", lambda: is_dev_root_set)
    monkeypatch.setattr(module, "machine_architecture", lambda: "amd64")
    monkeypatch.setattr(module, "require_architecture", lambda *args: None)
    monkeypatch.setattr(module, "run", fake_run)
    return module.EasyTierProvisioner(), ran, systemd, (core, cli)


def a_release(payload=b"the engine"):
    """A release archive shaped like the vendor's, and its digest.

    Args:
        payload: What each binary inside it holds.

    Returns:
        The archive's bytes and their sha256.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name in (EASYTIER_CORE_NAME, "easytier-web", EASYTIER_CLI_NAME):
            bundle.writestr(f"easytier-linux-x86_64/{name}", payload)
    archive = buffer.getvalue()
    return archive, hashlib.sha256(archive).hexdigest()


def test_a_carried_engine_is_never_downloaded_again(tmp_path, monkeypatch):
    provisioner, ran, _, _ = a_box(tmp_path, monkeypatch)

    result = provisioner.provision()

    assert not [command for command in ran if command[0] == "curl"]
    assert result.message == f"easytier {EASYTIER_VERSION}"


def test_the_unit_is_written_and_enabled_but_not_started(tmp_path, monkeypatch):
    """There is nothing to run on until a network is written, and the panel's
    apply is what starts it."""
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch)

    provisioner.provision()

    assert (systemd / EASYTIER_UNIT).read_text(encoding="utf-8") == PACKAGED_UNIT
    assert ["systemctl", "enable", EASYTIER_UNIT] in ran
    assert ["systemctl", "enable", "--now", EASYTIER_UNIT] not in ran


def test_a_unit_that_already_agrees_is_not_rewritten(tmp_path, monkeypatch):
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch)
    (systemd / EASYTIER_UNIT).write_text(PACKAGED_UNIT, encoding="utf-8")

    provisioner.provision()

    assert ["systemctl", "daemon-reload"] not in ran


def test_a_development_root_drives_no_units(tmp_path, monkeypatch):
    provisioner, ran, systemd, _ = a_box(tmp_path, monkeypatch, is_dev_root_set=True)

    provisioner.provision()

    assert ran == []
    assert not (systemd / EASYTIER_UNIT).exists()


def test_a_checkout_fetches_the_pinned_release(tmp_path, monkeypatch):
    archive, digest = a_release()
    provisioner, ran, _, (core, cli) = a_box(
        tmp_path, monkeypatch, is_engine_present=False, archive=archive
    )
    monkeypatch.setattr(module, "EASYTIER_SHA256", {"amd64": digest})

    result = provisioner.provision()

    assert [command for command in ran if command[0] == "curl"]
    assert core.read_bytes() == b"the engine"
    assert cli.read_bytes() == b"the engine"
    assert core.stat().st_mode & 0o111
    assert result.message == f"easytier {EASYTIER_VERSION}"


def test_a_release_that_is_not_what_is_pinned_is_refused(tmp_path, monkeypatch):
    archive, _ = a_release()
    provisioner, _, _, (core, _) = a_box(
        tmp_path, monkeypatch, is_engine_present=False, archive=archive
    )
    monkeypatch.setattr(module, "EASYTIER_SHA256", {"amd64": "00" * 32})

    with pytest.raises(ValueError):
        provisioner.provision()

    assert not core.exists()


def test_removing_it_keeps_the_binaries_and_the_network(tmp_path, monkeypatch):
    """The files are the package's, and the network is the panel's."""
    provisioner, ran, systemd, (core, _) = a_box(tmp_path, monkeypatch)
    (systemd / EASYTIER_UNIT).write_text(PACKAGED_UNIT, encoding="utf-8")

    provisioner.deprovision()

    assert core.is_file()
    assert not (systemd / EASYTIER_UNIT).exists()
    assert ["systemctl", "disable", "--now", EASYTIER_UNIT] in ran


def test_the_unit_name_is_one_name_everywhere():
    assert SYSTEM_OPTIONAL_UNITS["easytier"] == EASYTIER_UNIT
    assert MODULE_SPECS["easytier"].unit == EASYTIER_UNIT
    assert "/opt/neutrino/bin/easytier-core" in PACKAGED_UNIT
