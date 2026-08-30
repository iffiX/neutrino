"""Architecture names and the check that stands before a wrong download."""

import pytest

from neutrino_hub.modules.gitea.provisioner import download_url
from neutrino_hub.system import machine
from neutrino_hub.system.machine import machine_architecture, require_architecture


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


def test_the_gitea_download_follows_the_machine():
    """The bug this bans: an amd64 binary hardcoded onto a Raspberry Pi."""
    assert download_url("arm64").endswith("linux-arm64")
    assert download_url("amd64").endswith("linux-amd64")
