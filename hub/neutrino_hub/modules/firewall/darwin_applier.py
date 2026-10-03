"""Making macOS's application firewall allow the programs the hub runs.

That firewall allows programs rather than ports, so each program the hub
serves through is added with ``socketfilterfw --add`` and allowed with
``--unblockapp``. ``--listapps`` says which are there already, and a program
already allowed is left as it is.

Not pure: runs ``socketfilterfw``.
"""

from pathlib import PurePosixPath

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_DARWIN_ALLOWED,
    FIREWALL_DARWIN_BLOCKED,
    FIREWALL_DARWIN_LIST_LINE,
    FIREWALL_DARWIN_TOOL,
)
from neutrino_hub.utils.subprocess_run import run as run_command


def listed_programs(listing: str) -> dict:
    """The programs ``socketfilterfw --listapps`` names, and whether each is allowed.

    Args:
        listing: What the tool printed: a numbered line per program, and the
            line after it saying whether incoming connections are allowed.

    Returns:
        Program path to True when allowed, False when blocked.
    """
    programs = {}
    current = ""
    for line in listing.splitlines():
        match = FIREWALL_DARWIN_LIST_LINE.match(line)
        if match:
            current = match.group(1)
            programs[current] = False
            continue
        if current and FIREWALL_DARWIN_ALLOWED in line:
            programs[current] = True
        elif current and FIREWALL_DARWIN_BLOCKED in line:
            programs[current] = False
    return programs


class FirewallDarwinApplier:
    """Drives the hub's programs in macOS's application firewall."""

    def __init__(self, *, run=None):
        """
        Args:
            run: Runs one command, as
                :func:`neutrino_hub.utils.subprocess_run.run` does; None is
                that function.
        """
        self._run = run if run is not None else run_command

    def apply(self, programs: list) -> list:
        """Allow incoming connections to each program.

        Args:
            programs: The program paths the renderer gave.

        Returns:
            One line per program added or allowed; empty when each was
            allowed already.

        Raises:
            subprocess.CalledProcessError: When the tool refuses.
        """
        held = self._held()
        notes = []
        for program in programs:
            if held.get(program) is True:
                continue
            if program not in held:
                self._run([FIREWALL_DARWIN_TOOL, "--add", program])
            self._run([FIREWALL_DARWIN_TOOL, "--unblockapp", program])
            notes.append(f"firewall allows {PurePosixPath(program).name}")
        return notes

    def remove(self, programs: list) -> list:
        """Take each of these programs out of the firewall's list.

        Args:
            programs: The program paths.

        Returns:
            One line per program removed.

        Raises:
            subprocess.CalledProcessError: When the tool refuses.
        """
        held = self._held()
        notes = []
        for program in programs:
            if program not in held:
                continue
            self._run([FIREWALL_DARWIN_TOOL, "--remove", program])
            notes.append(f"firewall forgot {PurePosixPath(program).name}")
        return notes

    def _held(self) -> dict:
        """The programs the firewall lists now; empty when it cannot be read."""
        result = self._run([FIREWALL_DARWIN_TOOL, "--listapps"], is_checked=False)
        if not result.is_success:
            return {}
        return listed_programs(result.stdout)
