"""What the agent's relays need from Linux: the Podman bridges, and their rules in ufw and firewalld.

A Podman bridge is an interface named ``podmanN`` by netavark or
``cni-podmanN`` by CNI; its IPv4 address is the gateway its containers reach
the machine at. The interface names come from the kernel's own list, and
``ip -j -4 addr`` is run only while one of them names a bridge.

Each relayed port gets one rule in each firewall that runs on the machine:
in ufw where ``ufw status`` says ``Status: active``, the rule ``allow in on
<bridge> to <gateway> port <port> proto tcp`` with the comment
``neutrino_agent_relay``; in firewalld where ``firewall-cmd --state`` says
``running``, a rich rule from the bridge's subnet to the gateway's port, in
the bridge's zone or the default zone while the bridge is in none, written
to the runtime and to the permanent configuration. On plain nftables nothing
is added. The agent's own rules are found by ufw's comment and by
firewalld's rule text, and a rule of the agent's that no relay asks for is
removed.

Not pure: reads the kernel's interfaces, runs ``ip``, ``ufw`` and
``firewall-cmd``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess

from neutrino_agent.constants import (
    AGENT_RELAY_BRIDGE_PATTERN,
    AGENT_RELAY_COMMAND_LOCALE,
    AGENT_RELAY_FIREWALL_TIMEOUT_S,
    AGENT_RELAY_FIREWALLD,
    AGENT_RELAY_FIREWALLD_RULE_WORDS,
    AGENT_RELAY_FIREWALLD_RUNNING,
    AGENT_RELAY_IP_ADDR_COMMAND,
    AGENT_RELAY_IP_ADDR_TIMEOUT_S,
    AGENT_RELAY_RULE_COMMENT,
    AGENT_RELAY_UFW,
    AGENT_RELAY_UFW_ACTIVE,
)
from neutrino_agent.platforms.base import RelayAddress, RelayRule

BRIDGE_NAME = re.compile(AGENT_RELAY_BRIDGE_PATTERN)


def is_bridge_name(name: str) -> bool:
    """Whether an interface name is a Podman bridge's.

    Args:
        name: The interface's name.

    Returns:
        True for ``podmanN`` and ``cni-podmanN``.
    """
    return bool(BRIDGE_NAME.match(name))


def bridges_from(entries) -> list:
    """The Podman bridges in what ``ip -j -4 addr`` printed, each with its IPv4 addresses.

    Args:
        entries: The parsed output, one entry per interface.

    Returns:
        One :class:`RelayAddress` per IPv4 address on a bridge, in the
        output's order; an entry that is not a dict, names no bridge or
        has no index is left out.
    """
    found = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("ifname", "") or "")
        index = entry.get("ifindex")
        if not is_bridge_name(name) or not isinstance(index, int) or index <= 0:
            continue
        for info in entry.get("addr_info", []) or []:
            if not isinstance(info, dict) or info.get("family") != "inet":
                continue
            address = str(info.get("local", "") or "")
            prefix = info.get("prefixlen")
            if not address or not isinstance(prefix, int):
                continue
            found.append(
                RelayAddress(
                    interface=name, index=index, address=address, prefix=prefix
                )
            )
    return found


def read_bridges(*, names=socket.if_nameindex, run=subprocess.run) -> list:
    """The Podman bridges on this machine with their IPv4 addresses, read now.

    Args:
        names: Lists the kernel's interfaces as ``(index, name)``.
        run: Runs ``ip`` as :func:`subprocess.run` does.

    Returns:
        One :class:`RelayAddress` per address; empty while no interface
        names a bridge, and when ``ip`` cannot run, fails or prints no JSON.
    """
    try:
        listed = names()
    except OSError:
        return []
    if not any(is_bridge_name(name) for _index, name in listed):
        return []
    try:
        result = run(
            list(AGENT_RELAY_IP_ADDR_COMMAND),
            capture_output=True,
            text=True,
            timeout=AGENT_RELAY_IP_ADDR_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    try:
        entries = json.loads(result.stdout or "")
    except ValueError:
        return []
    return bridges_from(entries)


def subnet_of(rule: RelayRule) -> str:
    """The network a rule's interface holds, as ``<network>/<prefix>``.

    Args:
        rule: The rule.

    Returns:
        The network; the address alone as a ``/32`` when the prefix is 0.
    """
    prefix = rule.prefix if rule.prefix > 0 else 32
    return str(ipaddress.ip_network(f"{rule.address}/{prefix}", strict=False))


def ufw_rule_words(interface: str, address: str, port: int) -> list:
    """The words of the agent's ufw rule for one relay, after ``ufw`` and its verb.

    Args:
        interface: The bridge.
        address: The gateway.
        port: The relayed port.

    Returns:
        ``allow in on <bridge> to <gateway> port <port> proto tcp comment
        neutrino_agent_relay`` as words.
    """
    return [
        "allow",
        "in",
        "on",
        interface,
        "to",
        address,
        "port",
        str(port),
        "proto",
        "tcp",
        "comment",
        AGENT_RELAY_RULE_COMMENT,
    ]


def ufw_rules_from(text: str) -> set:
    """The agent's rules among what ``ufw show added`` printed.

    Args:
        text: The output: a heading, then one ``ufw <rule>`` line per rule.

    Returns:
        ``(interface, address, port)`` of each ``allow in on`` rule to one
        address and port over TCP that carries the agent's comment.
    """
    found = set()
    for line in text.splitlines():
        try:
            words = shlex.split(line)
        except ValueError:
            continue
        if len(words) < 5 or words[:4] != [AGENT_RELAY_UFW, "allow", "in", "on"]:
            continue
        interface, rest = words[4], words[5:]
        if len(rest) < 2 or rest[-2:] != ["comment", AGENT_RELAY_RULE_COMMENT]:
            continue
        rest = rest[:-2]
        if "from" in rest:
            at = rest.index("from")
            if rest[at + 1 : at + 2] != ["any"]:
                continue
            del rest[at : at + 2]
        if len(rest) != 6 or rest[0] != "to" or rest[2] != "port":
            continue
        if rest[4:] != ["proto", "tcp"] or not rest[3].isdigit():
            continue
        found.add((interface, rest[1], int(rest[3])))
    return found


def firewalld_rich_rule(rule: RelayRule) -> str:
    """The agent's rich rule for one relay.

    Args:
        rule: The relay's rule.

    Returns:
        ``rule family="ipv4" source address="<subnet>" destination
        address="<gateway>/32" port port="<port>" protocol="tcp" accept``.
    """
    return (
        f'rule family="ipv4" source address="{subnet_of(rule)}" '
        f'destination address="{rule.address}/32" '
        f'port port="{rule.port}" protocol="tcp" accept'
    )


def firewalld_rule_of(text: str) -> "tuple | None":
    """The values of a rich rule of the agent's shape.

    Args:
        text: One rich rule as firewalld prints it.

    Returns:
        ``(subnet, address, port)``, the subnet as a network and the
        address without its ``/32``; None for a rule of any other shape.
    """
    words = text.split()
    if len(words) != len(AGENT_RELAY_FIREWALLD_RULE_WORDS):
        return None
    values = []
    for word, expected in zip(words, AGENT_RELAY_FIREWALLD_RULE_WORDS):
        if expected.endswith("="):
            if not word.startswith(expected + '"') or not word.endswith('"'):
                return None
            values.append(word[len(expected) + 1 : -1])
        elif word != expected:
            return None
    subnet, address, port = values
    if address.endswith("/32"):
        address = address[: -len("/32")]
    try:
        subnet = str(ipaddress.ip_network(subnet, strict=False))
        address = str(ipaddress.IPv4Address(address))
    except ValueError:
        return None
    if not port.isdigit():
        return None
    return subnet, address, int(port)


def firewalld_rules_from(text: str) -> dict:
    """The agent's rich rules in what ``firewall-cmd --list-all-zones`` printed.

    Args:
        text: The output: each zone's name at the start of a line, then its
            settings indented, its rich rules among them.

    Returns:
        ``(zone, subnet, address, port)`` of each rule of the agent's shape,
        to the rule's text as printed.
    """
    found = {}
    zone = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            zone = line.split()[0]
            continue
        text_of_rule = line.strip()
        values = firewalld_rule_of(text_of_rule)
        if zone and values is not None:
            found[(zone, *values)] = text_of_rule
    return found


def command_environment() -> dict:
    """The environment a firewall command runs with: this process's, in the C locale."""
    return dict(
        os.environ,
        LC_ALL=AGENT_RELAY_COMMAND_LOCALE,
        LANG=AGENT_RELAY_COMMAND_LOCALE,
    )


def run_firewall(argv: list) -> subprocess.CompletedProcess:
    """Run one firewall command, its output kept, never raising for its exit code.

    Args:
        argv: The command.

    Returns:
        What it did.

    Raises:
        OSError: When the program cannot start.
        subprocess.TimeoutExpired: When it runs past the timeout.
    """
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=AGENT_RELAY_FIREWALL_TIMEOUT_S,
        env=command_environment(),
    )


class LinuxRelayFirewall:
    """The relays' rules in ufw and firewalld, made to match the relays."""

    def __init__(self, *, run=run_firewall):
        """
        Args:
            run: Runs one command and returns what it did, with
                ``returncode``, ``stdout`` and ``stderr``.
        """
        self._run = run

    def sync(self, rules: frozenset) -> list:
        """Give each firewall that runs one rule per relay, and take away the
        agent's rules no relay asks for.

        Args:
            rules: One :class:`RelayRule` per relay the agent opens.

        Returns:
            What changed, one line each.

        Raises:
            OSError: When a firewall command cannot start.
            subprocess.SubprocessError: When one runs past its timeout or
                fails.
        """
        lines = []
        if self._is_ufw_active():
            lines += self._sync_ufw(rules)
        if self._is_firewalld_running():
            lines += self._sync_firewalld(rules)
        return lines

    def _is_ufw_active(self) -> bool:
        """Whether ``ufw status`` says ``Status: active``; False with no ufw."""
        try:
            done = self._run([AGENT_RELAY_UFW, "status"])
        except FileNotFoundError:
            return False
        lines = (done.stdout or "").splitlines()
        return (
            done.returncode == 0
            and bool(lines)
            and lines[0].strip() == (AGENT_RELAY_UFW_ACTIVE)
        )

    def _is_firewalld_running(self) -> bool:
        """Whether ``firewall-cmd --state`` says ``running``; False with no firewalld."""
        try:
            done = self._run([AGENT_RELAY_FIREWALLD, "--state"])
        except FileNotFoundError:
            return False
        return (
            done.returncode == 0
            and (done.stdout or "").strip() == AGENT_RELAY_FIREWALLD_RUNNING
        )

    def _sync_ufw(self, rules: frozenset) -> list:
        """Add the missing ufw rules and delete the agent's others."""
        found = ufw_rules_from(self._checked([AGENT_RELAY_UFW, "show", "added"]))
        wanted = {(rule.interface, rule.address, rule.port) for rule in rules}
        lines = []
        for interface, address, port in sorted(wanted - found):
            self._checked([AGENT_RELAY_UFW, *ufw_rule_words(interface, address, port)])
            lines.append(
                f"added ufw rule: allow in on {interface} to {address} "
                f"port {port} proto tcp"
            )
        for interface, address, port in sorted(found - wanted):
            self._checked(
                [
                    AGENT_RELAY_UFW,
                    "--force",
                    "delete",
                    *ufw_rule_words(interface, address, port),
                ]
            )
            lines.append(
                f"removed ufw rule: allow in on {interface} to {address} "
                f"port {port} proto tcp"
            )
        return lines

    def _sync_firewalld(self, rules: frozenset) -> list:
        """Add the missing rich rules and remove the agent's others, at runtime and permanently."""
        wanted = {}
        default_zone = ""
        zones = {}
        for rule in rules:
            if rule.interface not in zones:
                zone = self._zone_of(rule.interface)
                if not zone:
                    if not default_zone:
                        default_zone = self._checked(
                            [AGENT_RELAY_FIREWALLD, "--get-default-zone"]
                        ).strip()
                    zone = default_zone
                zones[rule.interface] = zone
            key = (zones[rule.interface], subnet_of(rule), rule.address, rule.port)
            wanted[key] = firewalld_rich_rule(rule)
        lines = []
        for scope in ((), ("--permanent",)):
            found = firewalld_rules_from(
                self._checked([AGENT_RELAY_FIREWALLD, *scope, "--list-all-zones"])
            )
            where = "permanent" if scope else "runtime"
            for key in sorted(set(wanted) - set(found)):
                self._checked(
                    [
                        AGENT_RELAY_FIREWALLD,
                        *scope,
                        f"--zone={key[0]}",
                        f"--add-rich-rule={wanted[key]}",
                    ]
                )
                lines.append(
                    f"added firewalld rule in {key[0]} ({where}): {wanted[key]}"
                )
            for key in sorted(set(found) - set(wanted)):
                self._checked(
                    [
                        AGENT_RELAY_FIREWALLD,
                        *scope,
                        f"--zone={key[0]}",
                        f"--remove-rich-rule={found[key]}",
                    ]
                )
                lines.append(
                    f"removed firewalld rule from {key[0]} ({where}): {found[key]}"
                )
        return lines

    def _zone_of(self, interface: str) -> str:
        """The zone firewalld puts one interface in; empty while it is in none."""
        done = self._run(
            [AGENT_RELAY_FIREWALLD, f"--get-zone-of-interface={interface}"]
        )
        return (done.stdout or "").strip() if done.returncode == 0 else ""

    def _checked(self, argv: list) -> str:
        """Run one command and hand back its output.

        Raises:
            subprocess.CalledProcessError: When it exits other than 0.
        """
        done = self._run(argv)
        if done.returncode != 0:
            raise subprocess.CalledProcessError(
                done.returncode, argv, output=done.stdout, stderr=done.stderr
            )
        return done.stdout or ""
