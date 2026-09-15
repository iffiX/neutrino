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
