"""Making Windows Firewall allow the ports the hub serves.

Reads the rules named ``neutrino_hub_*``, then creates the missing ones with
``New-NetFirewallRule``, changes the ones whose port moved with
``Set-NetFirewallRule`` and removes the ones no purpose names any more with
``Remove-NetFirewallRule``. A pass that finds every rule as it should be
changes nothing.

Not pure: runs PowerShell.
"""

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_RULE_PREFIX,
    FIREWALL_WINDOWS_CHANGE_SCRIPT,
    FIREWALL_WINDOWS_DESCRIPTION,
    FIREWALL_WINDOWS_READ_SCRIPT,
)
from neutrino_hub.system.powershell_run import listed, run_powershell


def _document(rule) -> dict:
    """One rule as the script reads it."""
    return {"name": rule.name, "protocol": rule.protocol, "port": str(rule.port)}


class FirewallWindowsApplier:
    """Drives the hub's own rules in Windows Firewall."""

    def __init__(self, *, powershell=None):
        """
        Args:
            powershell: Runs one script with a document, as
                :func:`neutrino_hub.system.powershell_run.run_powershell`
                does; None is that function.
        """
        self._powershell = powershell if powershell is not None else run_powershell

    def apply(self, rules: list) -> list:
        """Make the hub's rules exactly these.

        Args:
            rules: The :class:`neutrino_hub.modules.firewall.renderer.FirewallPortRule`
                list the renderer gave.

        Returns:
            One line per rule created, changed or removed; empty when nothing
            changed.

        Raises:
            OSError: When PowerShell cannot run or a cmdlet refuses.
        """
        held = self._held()
        wanted = {rule.name: rule for rule in rules}
        create = [rule for name, rule in wanted.items() if name not in held]
        update = [
            rule
            for name, rule in wanted.items()
            if name in held and held[name] != (rule.protocol, str(rule.port))
        ]
        remove = sorted(name for name in held if name not in wanted)
        if not (create or update or remove):
            return []
        self._change(create=create, update=update, remove=remove)
        return (
            [f"firewall opened {rule.name}" for rule in create]
            + [f"firewall moved {rule.name} to {rule.port}" for rule in update]
            + [f"firewall closed {name}" for name in remove]
        )

    def remove(self) -> list:
        """Take every rule of the hub's away.

        Returns:
            One line per rule removed.

        Raises:
            OSError: When PowerShell cannot run or a cmdlet refuses.
        """
        held = sorted(self._held())
        if not held:
            return []
        self._change(create=[], update=[], remove=held)
        return [f"firewall closed {name}" for name in held]

    def _held(self) -> dict:
        """The hub's rules as Windows holds them: name to protocol and port."""
        answer = self._powershell(
            FIREWALL_WINDOWS_READ_SCRIPT, {"prefix": FIREWALL_RULE_PREFIX}
        )
        held = {}
        for entry in listed(answer.get("rules")):
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            held[str(entry["name"])] = (
                str(entry.get("protocol") or "").upper(),
                str(entry.get("port") or ""),
            )
        return held

    def _change(self, *, create: list, update: list, remove: list) -> None:
        """Run the one script that removes, changes and creates."""
        self._powershell(
            FIREWALL_WINDOWS_CHANGE_SCRIPT,
            {
                "description": FIREWALL_WINDOWS_DESCRIPTION,
                "create": [_document(rule) for rule in create],
                "update": [_document(rule) for rule in update],
                "remove": list(remove),
            },
        )
