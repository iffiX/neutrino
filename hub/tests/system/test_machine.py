"""Architecture names, the machine id, and the check before a wrong download."""

import pytest

from neutrino_hub.system import machine
from neutrino_hub.system.machine import (
    machine_architecture,
    machine_id,
    require_architecture,
)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("x86_64", "amd64"),
        ("aarch64", "arm64"),
        # 32-bit Raspberry Pi OS, both generations of Pi.
        ("armv6l", "arm-6"),
        ("armv7l", "arm-6"),
    ],
)
def test_kernel_names_normalize_to_release_names(monkeypatch, raw, normalized):
    monkeypatch.setattr(machine.platform, "machine", lambda: raw)

    assert machine_architecture() == normalized


def test_an_unknown_machine_reports_itself_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(machine.platform, "machine", lambda: "riscv64")

    assert machine_architecture() == "riscv64"


def test_a_star_declaration_accepts_any_machine(monkeypatch):
    monkeypatch.setattr(machine.platform, "machine", lambda: "riscv64")

    require_architecture(("*",), "anything")


def test_an_unsupported_machine_is_refused_by_name(monkeypatch):
    monkeypatch.setattr(machine.platform, "machine", lambda: "riscv64")

    with pytest.raises(RuntimeError, match="riscv64"):
        require_architecture(("amd64", "arm64"), "gitea")


def test_the_machine_id_is_the_file_without_its_newline(monkeypatch, tmp_path):
    path = tmp_path / "machine-id"
    path.write_text("0123456789abcdef0123456789abcdef\n")
    monkeypatch.setattr(machine, "MACHINE_ID_PATH", path)

    assert machine_id() == "0123456789abcdef0123456789abcdef"


def test_a_missing_machine_id_reads_as_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(machine, "MACHINE_ID_PATH", tmp_path / "machine-id")

    assert machine_id() == ""


def test_an_empty_machine_id_reads_as_empty(monkeypatch, tmp_path):
    path = tmp_path / "machine-id"
    path.write_text("\n")
    monkeypatch.setattr(machine, "MACHINE_ID_PATH", path)

    assert machine_id() == ""


def test_macos_is_its_own_family_and_reads_the_firmware_id(on_darwin, monkeypatch):
    from tests.conftest import FakeTools

    tools = FakeTools()
    tools.answers[("ioreg", "-rd1", "-c", "IOPlatformExpertDevice")] = (
        '  "IOPlatformUUID" = "4C4C4544-0042-3510-8048-B4C04F4E4D32"\n'
    )
    monkeypatch.setattr(machine, "run", tools)

    assert machine.distribution_family() == "darwin"
    assert machine_id() == "4C4C4544-0042-3510-8048-B4C04F4E4D32"
    assert machine.distribution_name().startswith("macOS")


def test_windows_is_its_own_family_and_reads_the_registry(on_windows, monkeypatch):
    import sys
    import types

    registry = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM",
        KEY_READ=0x20019,
        opened=[],
    )

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *details):
            return False

    def open_key(root, path, reserved, access):
        registry.opened.append((root, path, access))
        return Key()

    registry.OpenKey = open_key
    registry.QueryValueEx = lambda key, name: (
        "b7f4c2d0-1111-2222-3333-444455556666",
        1,
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)

    assert machine.distribution_family() == "windows"
    assert machine_id() == "b7f4c2d0-1111-2222-3333-444455556666"
    assert registry.opened == [
        ("HKLM", "SOFTWARE\\Microsoft\\Cryptography", 0x20019 | 0x0100)
    ]
    assert machine.distribution_name().startswith("Windows")
