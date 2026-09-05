"""Running something outside the panel's own sandbox.

The panel's unit is hardened: root, but with `NoNewPrivileges` and a set of
systemd's sandboxing directives. Under `NoNewPrivileges` systemd installs the
seccomp filters those directives need, and the effective capability set loses
`CAP_SETUID` — measured on Debian 12, where `NoNewPrivileges` plus **any one**
of the other directives is enough to lose it. Without them systemd applies no
filter at all, which is why taking `NoNewPrivileges` out appears to fix it and
is the one thing that must not be done ([../../../docs/standard/design/privilege.md](../../../docs/standard/design/privilege.md)).

Installing software is what runs into this. apt drops to the `_apt` account to
fetch, cannot, and every download dies with `seteuid 42 failed`. A vendor's
installer piped to `sh` hits the same wall a level down, where no flag of ours
reaches it.

So an install is handed to systemd instead of run here: a transient unit is a
unit of its own, with its own (default, unhardened) properties. The panel's
hardening is unchanged, apt keeps its own sandbox, and the escape is named at
the few call sites that install rather than being a hole in `run`.
"""

import os
import shutil

# Wait for it, and pass its streams straight through, so a caller cannot tell
# this from having run the command itself. `--collect` drops the unit's record
# afterwards, which is what keeps a box that installs often from filling up
# with finished transient units.
SANDBOX_SYSTEMD_RUN = (
    "systemd-run",
    "--quiet",
    "--wait",
    "--pipe",
    "--collect",
)
# systemd sets this for every unit invocation, so its presence is the honest
# test of "this process is inside a unit". A checkout run from a shell has no
# sandbox to escape and gets the command unchanged.
SANDBOX_UNIT_MARKER = "INVOCATION_ID"


def outside_sandbox(command: list) -> list:
    """The same command, to be run outside this unit's sandbox.

    Args:
        command: The argument vector.

    Returns:
        It wrapped in a transient unit, or unchanged where there is no
        sandbox to leave: a working copy run from a shell, or a machine
        whose systemd offers no ``systemd-run``.
    """
    if not is_sandboxed():
        return list(command)
    return [*SANDBOX_SYSTEMD_RUN, "--", *command]


def outside_sandbox_interactive(command: list) -> list:
    """The same command outside the sandbox, kept on the caller's terminal.

    For the commands that need a tty — a shell into a container — where
    ``--pipe`` would hand them pipes and their tty allocation would fail.

    Args:
        command: The argument vector.

    Returns:
        It wrapped in a transient unit on this terminal, or unchanged where
        there is no sandbox to leave.
    """
    if not is_sandboxed():
        return list(command)
    return [
        "systemd-run",
        "--quiet",
        "--collect",
        "--pty",
        "--wait",
        "--",
        *command,
    ]


def is_sandboxed() -> bool:
    """Whether this process is inside a unit whose sandbox can be left.

    Returns:
        True when systemd started this process and ``systemd-run`` is there
        to start another.
    """
    return bool(os.environ.get(SANDBOX_UNIT_MARKER)) and bool(
        shutil.which("systemd-run")
    )
