"""Leaving the panel's sandbox to install something.

The panel's unit is root with `NoNewPrivileges` and systemd's sandboxing, and
under those the effective capability set loses `CAP_SETUID`. apt drops to the
`_apt` account to fetch and cannot, so every download dies with
`seteuid 42 failed` — measured on Debian 12, panel-driven installs of netbird,
podman and zfs all failing that way while the same installs from a shell
succeeded.
"""

from neutrino_hub.system import sandbox
from neutrino_hub.system.sandbox import outside_sandbox


def test_a_command_inside_a_unit_is_handed_to_systemd(monkeypatch):
    monkeypatch.setenv(sandbox.SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert outside_sandbox(["apt-get", "install", "-y", "podman"]) == [
        "systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--",
        "apt-get",
        "install",
        "-y",
        "podman",
    ]


def test_a_working_copy_has_no_sandbox_to_leave(monkeypatch):
    """`nhub run` from a shell is not inside a unit, so there is nothing to
    escape and wrapping would only add a dependency on systemd."""
    monkeypatch.delenv(sandbox.SANDBOX_UNIT_MARKER, raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert outside_sandbox(["apt-get", "update"]) == ["apt-get", "update"]


def test_a_machine_without_systemd_run_gets_the_command_itself(monkeypatch):
    """Better a command that runs than one that cannot be started at all."""
    monkeypatch.setenv(sandbox.SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)

    assert outside_sandbox(["apt-get", "update"]) == ["apt-get", "update"]


def test_the_command_is_copied_rather_than_shared(monkeypatch):
    """The caller's list is its own; a wrapper that appended to it would grow
    the command every time it was reused."""
    monkeypatch.delenv(sandbox.SANDBOX_UNIT_MARKER, raising=False)
    command = ["apt-get", "update"]

    wrapped = outside_sandbox(command)
    wrapped.append("--dry-run")

    assert command == ["apt-get", "update"]


def test_the_separator_keeps_a_command_from_being_read_as_options(monkeypatch):
    """Without `--`, a package manager's own flags would be read by
    systemd-run: `apt-get -q` is systemd-run's `-q` first."""
    monkeypatch.setenv(sandbox.SANDBOX_UNIT_MARKER, "b8f0b4c0")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    wrapped = outside_sandbox(["apt-get", "-q", "update"])

    assert wrapped[wrapped.index("--") + 1] == "apt-get"


def test_the_interactive_escape_keeps_the_terminal(monkeypatch):
    """A shell into a container needs a tty, so its escape rides --pty."""
    from neutrino_hub.system import sandbox

    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/bin/systemd-run")

    wrapped = sandbox.outside_sandbox_interactive(["podman", "exec", "-it", "kuma"])

    assert wrapped[:6] == [
        "systemd-run",
        "--quiet",
        "--collect",
        "--pty",
        "--wait",
        "--",
    ]
    assert wrapped[6:] == ["podman", "exec", "-it", "kuma"]


def test_the_interactive_escape_is_a_no_op_outside_a_unit(monkeypatch):
    from neutrino_hub.system import sandbox

    monkeypatch.delenv("INVOCATION_ID", raising=False)

    command = ["podman", "exec", "-it", "kuma"]
    assert sandbox.outside_sandbox_interactive(command) == command
