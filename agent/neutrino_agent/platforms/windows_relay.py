"""What the agent's relays need from Windows: WSL's vEthernet adapter, and the relays' rules in Windows Firewall.

The Podman machine runs in WSL's NAT mode, where ``host.containers.internal``
is the computer's address on the adapter whose name starts ``vEthernet
(WSL``. Each relayed port gets one inbound allow rule for TCP to the port,
named ``neutrino_agent_relay_<port>`` and scoped to that adapter by its
alias; the agent finds its rules by that name, and removes each one no relay
asks for. The rules are read and written through the agent's PowerShell
host.

Pure: the decisions over what the adapters and the host report.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ipaddress

from neutrino_agent.constants import (
    AGENT_RELAY_RULE_PREFIX,
    AGENT_RELAY_WSL_ADAPTER_PREFIX,
)
from neutrino_agent.platforms.base import RelayAddress


def wsl_addresses_from(interfaces: list) -> list:
    """The IPv4 addresses of WSL's vEthernet adapter among the adapters read.

    Args:
        interfaces: ``[{"name", "mac", "addresses"}]`` as iphlpapi gave them.

    Returns:
        One :class:`RelayAddress` per IPv4 address on an adapter whose name
        starts ``vEthernet (WSL``, with no index and no prefix.
    """
    found = []
    for interface in interfaces:
        name = str(interface.get("name", "") or "")
        if not name.startswith(AGENT_RELAY_WSL_ADAPTER_PREFIX):
            continue
        for address in interface.get("addresses", ()) or ():
            try:
                ipaddress.IPv4Address(str(address))
            except ValueError:
                continue
            found.append(
                RelayAddress(interface=name, index=0, address=str(address), prefix=0)
            )
    return found


def rule_name(port: int) -> str:
    """The name of the agent's rule for one relayed port.

    Args:
        port: The port.

    Returns:
        ``neutrino_agent_relay_<port>``.
    """
    return f"{AGENT_RELAY_RULE_PREFIX}{port}"


def wanted_rules(rules: frozenset) -> dict:
    """The rules Windows Firewall is to hold, one per relayed port.

    Args:
        rules: One :class:`RelayRule` per relay the agent opens.

    Returns:
        Each rule's name to ``{name, port, alias}``; of two relays on one
        port, the adapter that sorts first names the rule.
    """
    wanted = {}
    for rule in sorted(rules, key=lambda held: (held.port, held.interface)):
        name = rule_name(rule.port)
        wanted.setdefault(
            name, {"name": name, "port": str(rule.port), "alias": rule.interface}
        )
    return wanted


def rule_changes(rules: frozenset, found: list) -> tuple:
    """What to add and what to remove so the firewall holds the wanted rules.

    Args:
        rules: One :class:`RelayRule` per relay the agent opens.
        found: The agent's rules the firewall holds, ``[{name, port,
            alias}]`` as the host read them.

    Returns:
        ``(add, remove)``: the rules to add, each ``{name, port, alias}``,
        and the names to remove; a rule whose port or adapter differs is
        removed and added again.
    """
    wanted = wanted_rules(rules)
    held = {}
    for entry in found:
        if isinstance(entry, dict) and str(entry.get("name", "")).startswith(
            AGENT_RELAY_RULE_PREFIX
        ):
            held[str(entry["name"])] = {
                "name": str(entry["name"]),
                "port": str(entry.get("port", "") or ""),
                "alias": str(entry.get("alias", "") or ""),
            }
    remove = sorted(name for name, entry in held.items() if wanted.get(name) != entry)
    add = [
        wanted[name] for name in sorted(wanted) if name not in held or name in remove
    ]
    return add, remove
