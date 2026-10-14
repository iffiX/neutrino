"""Keeping the hub's rich rules in firewalld, on a Linux hub where it runs.

A packet passes only when every table on its hook accepts it, so while
firewalld runs its zones must accept the hub's ports too. The hub's rules
are rich rules told from the person's by the priority they carry,
:data:`FIREWALL_FIREWALLD_PRIORITY`; every change is made to the runtime and
to the permanent configuration, and only the hub's own rules are added or
removed. Where firewalld is stopped, the removal edits the permanent
configuration with ``firewall-offline-cmd``.

Not pure: runs ``firewall-cmd``.
"""

import ipaddress

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_FIREWALLD_OFFLINE_TOOL,
    FIREWALL_FIREWALLD_PRIORITY,
    FIREWALL_FIREWALLD_RULE_FIELD,
    FIREWALL_FIREWALLD_RUNNING,
    FIREWALL_FIREWALLD_TIMEOUT_S,
    FIREWALL_FIREWALLD_TOOL,
)
from neutrino_hub.utils.subprocess_run import run as run_command


def parse_zones(listing: str) -> dict:
    """The zones ``firewall-cmd --list-all-zones`` prints.

    Args:
        listing: What the tool printed: each zone's name at the start of a
            line, its fields indented under it, and each rich rule on a line
            of its own after ``rich rules:``.

    Returns:
        Zone name to ``{"interfaces": [...], "rules": [...]}``.
    """
    zones: dict = {}
    current = None
    is_rich = False
    for line in listing.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            current = line.split()[0]
            zones[current] = {"interfaces": [], "rules": []}
            is_rich = False
            continue
        if current is None:
            continue
        text = line.strip()
        if is_rich and text.startswith("rule"):
            zones[current]["rules"].append(text)
            continue
        key, _, value = text.partition(":")
        is_rich = key == "rich rules"
        if is_rich and value.strip():
            zones[current]["rules"].append(value.strip())
        elif key == "interfaces":
            zones[current]["interfaces"] = value.split()
    return zones


def rule_key(rule: str) -> "tuple | None":
    """What one rich rule says, in a form two spellings of it compare in.

    Args:
        rule: A rich rule as printed or rendered.

    Returns:
        ``(family, source, port, protocol, action)`` for a rule carrying the
        hub's priority; None for every other rule.
    """
    fields = dict(FIREWALL_FIREWALLD_RULE_FIELD.findall(rule))
    if fields.get("priority") != str(FIREWALL_FIREWALLD_PRIORITY):
        return None
    source = fields.get("address", "")
    if source:
        try:
            source = str(ipaddress.ip_network(source, strict=False))
        except ValueError:
            pass
    return (
        fields.get("family", ""),
        source,
        fields.get("port", ""),
        fields.get("protocol", ""),
        rule.split()[-1] if rule.split() else "",
    )


def hub_rules(zones: dict) -> dict:
    """The hub's own rules in each zone.

    Args:
        zones: Zone to its rules, as printed or rendered.

    Returns:
        Zone to the rules among them carrying the hub's priority; a zone
        holding none is left out.
    """
    found = {}
    for zone, rules in zones.items():
        own = [rule for rule in rules if rule_key(rule) is not None]
        if own:
            found[zone] = own
    return found


def keyed(zones: dict) -> dict:
    """The hub's rules by zone, as sets of :func:`rule_key` answers.

    Args:
        zones: Zone to its rules.

    Returns:
        Zone to the keys of the hub's rules in it; a zone with none left out.
    """
    return {
        zone: {rule_key(rule) for rule in rules}
        for zone, rules in hub_rules(zones).items()
    }


class FirewallFirewalldApplier:
    """Drives the hub's own rich rules in firewalld."""

    def __init__(self, *, run=None):
        """
        Args:
            run: Runs one command, as
                :func:`neutrino_hub.utils.subprocess_run.run` does; None is
                that function.
        """
        self._run = run if run is not None else run_command

    def is_running(self) -> bool:
        """Whether firewalld runs.

        Returns:
            True when ``firewall-cmd --state`` says ``running``; False when
            it says otherwise or the tool is not installed.
        """
        result = self._run(
            [FIREWALL_FIREWALLD_TOOL, "--state"],
            is_checked=False,
            timeout_s=FIREWALL_FIREWALLD_TIMEOUT_S,
        )
        return result.is_success and result.stdout.strip() == FIREWALL_FIREWALLD_RUNNING

    def survey(self) -> tuple:
        """The runtime's zones of the devices and the hub's rules in it.

        Returns:
            Device name to its zone; the default zone, for a device in none;
            and zone to the hub's rules the runtime holds.

        Raises:
            subprocess.CalledProcessError: When firewall-cmd refuses.
            OSError: When it cannot run.
        """
        zones = self._zones(is_permanent=False)
        devices = {
            device: zone
            for zone, entry in zones.items()
            for device in entry["interfaces"]
        }
        default = self._firewall_cmd("--get-default-zone").stdout.strip()
        return devices, default, hub_rules(_rules_of(zones))

    def held(self) -> dict:
        """The hub's rules firewalld's runtime holds now.

        Returns:
            Zone to the rules.

        Raises:
            subprocess.CalledProcessError: When firewall-cmd refuses.
            OSError: When it cannot run.
        """
        return hub_rules(_rules_of(self._zones(is_permanent=False)))

    def apply(self, wanted: dict, *, held: dict) -> list:
        """Make the hub's rules exactly these, in the runtime and permanently.

        Args:
            wanted: Zone to the rules the hub needs there.
            held: Zone to the hub's rules the runtime holds now, as
                :meth:`survey` read them.

        Returns:
            One line per zone whose rules changed; empty when the runtime
            already held exactly these, in which case the permanent
            configuration is not read either.

        Raises:
            subprocess.CalledProcessError: When firewall-cmd refuses.
            OSError: When it cannot run.
        """
        if keyed(held) == keyed(wanted):
            return []
        notes = self._change(held, wanted, prefix=[])
        permanent = hub_rules(_rules_of(self._zones(is_permanent=True)))
        self._change(permanent, wanted, prefix=["--permanent"])
        return notes

    def remove(self) -> list:
        """Take every rule of the hub's out of firewalld.

        Returns:
            One line per zone the runtime held rules of the hub's in; with
            firewalld stopped, one per zone of the permanent configuration,
            edited with ``firewall-offline-cmd``.

        Raises:
            subprocess.CalledProcessError: When the tool refuses.
            OSError: When it cannot run.
        """
        if self.is_running():
            notes = self._change(self.held(), {}, prefix=[])
            permanent = hub_rules(_rules_of(self._zones(is_permanent=True)))
            self._change(permanent, {}, prefix=["--permanent"])
            return notes
        listing = self._run(
            [FIREWALL_FIREWALLD_OFFLINE_TOOL, "--list-all-zones"],
            is_checked=False,
            timeout_s=FIREWALL_FIREWALLD_TIMEOUT_S,
        )
        if not listing.is_success:
            return []
        stored = hub_rules(_rules_of(parse_zones(listing.stdout)))
        return self._change(stored, {}, prefix=[], tool=FIREWALL_FIREWALLD_OFFLINE_TOOL)

    def _change(
        self,
        held: dict,
        wanted: dict,
        *,
        prefix: list,
        tool: str = FIREWALL_FIREWALLD_TOOL,
    ) -> list:
        """Remove the held rules no longer wanted and add the missing ones."""
        notes = []
        for zone in sorted(set(held) | set(wanted)):
            wanted_keys = {rule_key(rule) for rule in wanted.get(zone, [])}
            held_keys = {rule_key(rule) for rule in held.get(zone, [])}
            removed = [
                rule for rule in held.get(zone, []) if rule_key(rule) not in wanted_keys
            ]
            added = [
                rule for rule in wanted.get(zone, []) if rule_key(rule) not in held_keys
            ]
            if removed:
                self._run(
                    [tool, *prefix, f"--zone={zone}"]
                    + [f"--remove-rich-rule={rule}" for rule in removed],
                    timeout_s=FIREWALL_FIREWALLD_TIMEOUT_S,
                )
            if added:
                self._run(
                    [tool, *prefix, f"--zone={zone}"]
                    + [f"--add-rich-rule={rule}" for rule in added],
                    timeout_s=FIREWALL_FIREWALLD_TIMEOUT_S,
                )
            if removed or added:
                notes.append(
                    f"firewalld zone {zone}: {len(added)} rules added, "
                    f"{len(removed)} removed"
                )
        return notes

    def _zones(self, *, is_permanent: bool) -> dict:
        """Every zone, as :func:`parse_zones` reads it."""
        words = ["--permanent"] if is_permanent else []
        return parse_zones(self._firewall_cmd(*words, "--list-all-zones").stdout)

    def _firewall_cmd(self, *words: str):
        """Run firewall-cmd with these words; its result."""
        return self._run(
            [FIREWALL_FIREWALLD_TOOL, *words], timeout_s=FIREWALL_FIREWALLD_TIMEOUT_S
        )


def _rules_of(zones: dict) -> dict:
    """Zone to its rich rules, of what :func:`parse_zones` read."""
    return {zone: entry["rules"] for zone, entry in zones.items()}
