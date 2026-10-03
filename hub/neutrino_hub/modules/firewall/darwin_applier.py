"""Making macOS's firewalls answer as the hub's exposure says.

The application firewall allows programs rather than ports, so each program
the hub serves through is added with ``socketfilterfw --add`` and allowed
with ``--unblockapp``. ``--listapps`` says which are there already, and a
program already allowed is left as it is.

The pf sub-anchor ``com.apple/neutrino_hub`` blocks the hub's ports on the
interfaces that are not exposed. Its rules are kept in a file under the
state root and loaded with ``pfctl -a <anchor> -f <file>`` at every routing
pass and when the service starts, since pf forgets them at boot.

Not pure: runs ``socketfilterfw`` and ``pfctl``.
"""

from pathlib import Path, PurePosixPath

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_DARWIN_ALLOWED,
    FIREWALL_DARWIN_BLOCKED,
    FIREWALL_DARWIN_LIST_LINE,
    FIREWALL_DARWIN_PF_ANCHOR,
    FIREWALL_DARWIN_PF_ENABLED,
    FIREWALL_DARWIN_PF_RULES_PATH,
    FIREWALL_DARWIN_TOOL,
)
from neutrino_hub.utils.json_file import write_generated
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

    def __init__(self, *, run=None, rules_path: Path | None = None):
        """
        Args:
            run: Runs one command, as
                :func:`neutrino_hub.utils.subprocess_run.run` does; None is
                that function.
            rules_path: Where the anchor's rules are kept between loads;
                None is :data:`FIREWALL_DARWIN_PF_RULES_PATH`.
        """
        self._run = run if run is not None else run_command
        self._rules_path = (
            rules_path if rules_path is not None else FIREWALL_DARWIN_PF_RULES_PATH
        )

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

    def load_anchor(self, rules: str) -> list:
        """Keep the anchor's rules and load them into pf.

        pf is turned on when it is off and the rules block anything.

        Args:
            rules: The anchor text the renderer gave; empty blocks nothing.

        Returns:
            One line when the rules differ from the ones kept before; empty
            otherwise.

        Raises:
            OSError: When the rules cannot be written or ``pfctl`` cannot run.
            subprocess.CalledProcessError: When ``pfctl`` refuses.
        """
        try:
            kept = self._rules_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            kept = None
        write_generated(self._rules_path, rules, mode=0o600)
        self._load_anchor(rules)
        if kept == rules:
            return []
        return [f"firewall anchor {FIREWALL_DARWIN_PF_ANCHOR} blocks {_count(rules)}"]

    def reload_anchor(self) -> None:
        """Load the kept rules into pf again, as the service does at start.

        Raises:
            OSError: When ``pfctl`` cannot run.
            subprocess.CalledProcessError: When ``pfctl`` refuses.
        """
        try:
            rules = self._rules_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        self._load_anchor(rules)

    def flush_anchor(self) -> list:
        """Empty the anchor and forget the kept rules.

        Returns:
            One line when there were rules kept.

        Raises:
            OSError: When ``pfctl`` cannot run.
        """
        self._run(
            ["pfctl", "-a", FIREWALL_DARWIN_PF_ANCHOR, "-F", "all"], is_checked=False
        )
        if not self._rules_path.exists():
            return []
        self._rules_path.unlink()
        return [f"firewall anchor {FIREWALL_DARWIN_PF_ANCHOR} flushed"]

    def _load_anchor(self, rules: str) -> None:
        """Load the kept file into the anchor; turn pf on when the rules need it."""
        self._run(
            ["pfctl", "-a", FIREWALL_DARWIN_PF_ANCHOR, "-f", str(self._rules_path)]
        )
        if not rules.strip():
            return
        info = self._run(["pfctl", "-s", "info"], is_checked=False)
        if FIREWALL_DARWIN_PF_ENABLED not in info.stdout:
            self._run(["pfctl", "-E"])

    def _held(self) -> dict:
        """The programs the firewall lists now; empty when it cannot be read."""
        result = self._run([FIREWALL_DARWIN_TOOL, "--listapps"], is_checked=False)
        if not result.is_success:
            return {}
        return listed_programs(result.stdout)


def _count(rules: str) -> str:
    """How many block lines the anchor holds, said in words."""
    count = sum(1 for line in rules.splitlines() if line.strip())
    return "nothing" if count == 0 else f"{count} rule{'s' if count != 1 else ''}"
