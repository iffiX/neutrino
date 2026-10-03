"""Making Windows Firewall allow the ports the hub serves.

Reads the rules named ``neutrino_hub_*``, then creates the missing ones with
``New-NetFirewallRule``, changes the ones whose port or interfaces moved with
``Set-NetFirewallRule`` and removes the ones no purpose names any more with
``Remove-NetFirewallRule``. Each rule is scoped with ``-InterfaceAlias`` to
the interfaces it answers on that Windows has an adapter by, and a rule left
with none is kept disabled. While an alias is left out or a rule is refused,
the change runs again after a wait, a bounded number of times; one refused
rule leaves the others applied. A pass that finds every rule as it should be
changes nothing.

Not pure: runs PowerShell.
"""

import time
from dataclasses import replace

from neutrino_hub.modules.firewall.constants import (
    FIREWALL_RULE_PREFIX,
    FIREWALL_WINDOWS_CHANGE_SCRIPT,
    FIREWALL_WINDOWS_RETRY_COUNT,
    FIREWALL_WINDOWS_RETRY_WAIT_S,
    FIREWALL_WINDOWS_DESCRIPTION,
    FIREWALL_WINDOWS_READ_SCRIPT,
)
from neutrino_hub.system.powershell_run import listed, run_powershell


def _document(rule) -> dict:
    """One rule as the script reads it."""
    return {
        "name": rule.name,
        "protocol": rule.protocol,
        "port": str(rule.port),
        "interfaces": list(rule.interfaces),
    }


def _held_shape(rule) -> tuple:
    """What a rule must look like in Windows: protocol, port, enabled, scope."""
    return (
        rule.protocol.upper(),
        str(rule.port),
        bool(rule.interfaces),
        _scope(rule.interfaces),
    )


def _change_note(rule, held: tuple) -> str:
    """One line saying how a held rule changed."""
    if held[1] != str(rule.port):
        return f"firewall moved {rule.name} to {rule.port}"
    if not rule.interfaces:
        return f"firewall disabled {rule.name}"
    return f"firewall scoped {rule.name} to {', '.join(rule.interfaces)}"


def _scope(interfaces) -> tuple:
    """Interface aliases in an order two scopes can be compared in."""
    return tuple(sorted(str(name).lower() for name in interfaces))


def _plan(held: dict, wanted: dict) -> tuple:
    """The rules to create and change, and the names to remove."""
    create = [rule for name, rule in wanted.items() if name not in held]
    update = [
        rule
        for name, rule in wanted.items()
        if name in held and held[name] != _held_shape(rule)
    ]
    remove = sorted(name for name in held if name not in wanted)
    return create, update, remove


def _by_name(entries, key: str) -> dict:
    """One member of each entry of the change's answer, by the rule it names."""
    return {
        str(entry["name"]): entry.get(key)
        for entry in listed(entries)
        if isinstance(entry, dict) and entry.get("name")
    }


def _is_settled(answer: dict) -> bool:
    """Whether a change left no alias out and had no rule refused."""
    return not (listed(answer.get("dropped")) or listed(answer.get("failed")))


def _refusal(rule, error) -> dict:
    """One rule Windows refused, as the routing pass reports it."""
    head = rule.name
    if rule.interfaces:
        head = f"{head} on {', '.join(rule.interfaces)}"
    return {"rule": rule.name, "detail": f"{head}: {error or 'refused'}"}


class FirewallWindowsApplier:
    """Drives the hub's own rules in Windows Firewall."""

    def __init__(self, *, powershell=None, sleep=None):
        """
        Args:
            powershell: Runs one script with a document, as
                :func:`neutrino_hub.system.powershell_run.run_powershell`
                does; None is that function.
            sleep: Waits a number of seconds between two runs of the
                change; None is :func:`time.sleep`.
        """
        self._powershell = powershell if powershell is not None else run_powershell
        self._sleep = sleep if sleep is not None else time.sleep

    def apply(self, rules: list) -> tuple:
        """Make the hub's rules exactly these.

        Args:
            rules: The :class:`neutrino_hub.modules.firewall.renderer.FirewallPortRule`
                list the renderer gave.

        Returns:
            The notes, one line per rule created, changed or removed and one
            per rule an alias was left out of; and the refusals, one
            ``{rule, detail}`` per rule Windows still refused after the last
            run. Both empty when nothing changed.

        Raises:
            OSError: When PowerShell cannot run or the script fails.
        """
        wanted = {rule.name: rule for rule in rules}
        held = self._held()
        create, update, remove = _plan(held, wanted)
        if not (create or update or remove):
            return [], []
        answer = self._change(create=create, update=update, remove=remove)
        for _ in range(FIREWALL_WINDOWS_RETRY_COUNT - 1):
            if _is_settled(answer):
                break
            self._sleep(FIREWALL_WINDOWS_RETRY_WAIT_S)
            again, changed, gone = _plan(self._held(), wanted)
            if not (again or changed or gone):
                answer = {}
                break
            answer = self._change(create=again, update=changed, remove=gone)
        dropped = _by_name(answer.get("dropped"), "interfaces")
        failed = _by_name(answer.get("failed"), "error")
        notes = [
            f"firewall opened {rule.name}" for rule in create if rule.name not in failed
        ]
        for rule in update:
            if rule.name in failed:
                continue
            left_out = set(_scope(listed(dropped.get(rule.name))))
            kept = tuple(
                name for name in rule.interfaces if name.lower() not in left_out
            )
            notes.append(_change_note(replace(rule, interfaces=kept), held[rule.name]))
        notes += [f"firewall closed {name}" for name in remove]
        notes += [
            f"firewall left {', '.join(map(str, listed(aliases)))} out of {name}:"
            " Windows has no adapter by that name"
            for name, aliases in dropped.items()
            if name not in failed
        ]
        refused = [
            _refusal(wanted[name], error)
            for name, error in failed.items()
            if name in wanted
        ]
        return notes, refused

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
        """The hub's rules as Windows holds them, shaped as :func:`_held_shape`."""
        answer = self._powershell(
            FIREWALL_WINDOWS_READ_SCRIPT, {"prefix": FIREWALL_RULE_PREFIX}
        )
        held = {}
        for entry in listed(answer.get("rules")):
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            is_enabled = bool(entry.get("is_enabled", True))
            held[str(entry["name"])] = (
                str(entry.get("protocol") or "").upper(),
                str(entry.get("port") or ""),
                is_enabled,
                _scope(listed(entry.get("interfaces"))) if is_enabled else (),
            )
        return held

    def _change(self, *, create: list, update: list, remove: list) -> dict:
        """Run the one script that removes, changes and creates; its answer."""
        return self._powershell(
            FIREWALL_WINDOWS_CHANGE_SCRIPT,
            {
                "description": FIREWALL_WINDOWS_DESCRIPTION,
                "create": [_document(rule) for rule in create],
                "update": [_document(rule) for rule in update],
                "remove": list(remove),
            },
        )
