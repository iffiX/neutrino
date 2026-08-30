"""Working out which uplink should carry traffic, and why.

The gateway ranks its own uplinks rather than asking to be told. Almost
everything the ranking needs is a fact the box can read — which uplinks share
one upstream line, which are wired, what each negotiated, whether the carrier
is up — and a person restating those as an ordering is a second copy to keep in
sync by hand.

Two ideas do the work.

**Uplinks that share an upstream are one line.** Two interfaces reaching the
same next hop are two ways onto one broadband connection, not two connections.
Only one of them can usefully carry traffic: balancing between them splits
flows over a single line for no gain, and having both hold addresses on one
segment is what makes a box answer its own ARP. So the second is put on
standby automatically, and nobody has to notice the problem to avoid it.

**Link speed is about the cable, not the line.** A gigabit port in front of a
300 Mbit connection is a 300 Mbit uplink. Speed and medium are therefore
tie-breakers, never the primary key, and the ranking is built only from things
that do not move: carrier, stated intent, medium, negotiated speed, then the
order the interfaces were configured in. Nothing here is measured, so nothing
here flaps — a ranking that changes with the wind drops every connection each
time it changes its mind.

Pure: this module takes a snapshot and returns a plan. Acting on the plan is
:mod:`neutrino_hub.modules.router.routes`.
"""

import ipaddress
from dataclasses import dataclass, field

from neutrino_hub.modules.router.constants import (
    ROUTER_METRIC_BACKUP,
    ROUTER_METRIC_BALANCE,
    ROUTER_POLICY_BALANCE,
)
from neutrino_hub.modules.router.interfaces import RouterInterface, RouterNetworkConfig

# How far apart consecutive uplinks' route metrics sit. Wide enough that the
# order is legible in `ip route`, narrow enough to stay well below the backup
# band.
METRIC_STEP = 10

MEDIUM_WIRED = "ethernet"
MEDIUM_WIRELESS = "wifi"


@dataclass
class UplinkFacts:
    """What the system says about one uplink, at one moment.

    Attributes:
        name: Interface name.
        medium: ``ethernet`` or ``wifi``.
        is_carrying: Whether the link is up and holds an address, which is the
            only sense in which an uplink is usable.
        gateway: Next hop currently reachable through it, or None.
        cidr: Its address with prefix, for spotting a shared segment when two
            uplinks have no gateway to compare.
        speed_mbps: Negotiated link speed, or None when unknown.
    """

    name: str
    medium: str = MEDIUM_WIRED
    is_carrying: bool = False
    gateway: str | None = None
    cidr: str | None = None
    speed_mbps: int | None = None


@dataclass
class PlannedUplink:
    """One uplink's place in the plan.

    Attributes:
        name: Interface name.
        line_id: Which upstream line it reaches.
        rank: Its position overall, 1 being the one traffic prefers.
        is_active: Whether it should be carrying traffic.
        route_metric: The metric its default route should have.
        reason: One phrase saying why it sits where it does, so the ranking can
            be shown rather than merely obeyed.
        facts: The snapshot it was ranked from.
    """

    name: str
    line_id: str
    rank: int
    is_active: bool
    route_metric: int
    reason: str
    facts: UplinkFacts


@dataclass
class UpstreamLine:
    """One physical path to the internet, and the uplinks that reach it.

    Attributes:
        id: Stable identifier — the shared next hop where there is one, else
            the shared subnet, else the single interface's own name.
        gateway: The next hop, when known.
        members: Its uplinks, best first.
    """

    id: str
    gateway: str | None
    members: list[PlannedUplink] = field(default_factory=list)

    @property
    def is_shared(self) -> bool:
        """Whether more than one interface reaches this line."""
        return len(self.members) > 1

    @property
    def is_carrying(self) -> bool:
        """Whether any of its uplinks is currently active."""
        return any(member.is_active for member in self.members)


@dataclass
class UplinkPlan:
    """What the gateway intends to do with its uplinks.

    Attributes:
        lines: The upstream lines, best first.
        uplinks: Every planned uplink, best first, across all lines.
    """

    lines: list[UpstreamLine] = field(default_factory=list)
    uplinks: list[PlannedUplink] = field(default_factory=list)

    @property
    def active(self) -> list[PlannedUplink]:
        """The uplinks that should carry traffic, best first."""
        return [uplink for uplink in self.uplinks if uplink.is_active]

    @property
    def is_balancing(self) -> bool:
        """Whether traffic is meant to be split across more than one uplink."""
        return len(self.active) > 1

    def uplink(self, name: str) -> PlannedUplink | None:
        """Find one uplink's plan by interface name.

        Args:
            name: Interface name.

        Returns:
            Its plan, or None when the interface is not an uplink.
        """
        for uplink in self.uplinks:
            if uplink.name == name:
                return uplink
        return None


def plan_uplinks(
    *, network: RouterNetworkConfig, facts: dict[str, UplinkFacts]
) -> UplinkPlan:
    """Decide which uplinks carry traffic and in what order.

    Args:
        network: The parsed router configuration, for roles, intents and the
            failover-or-balance policy.
        facts: What the system currently says about each interface, keyed by
            name. An interface with no entry is treated as not carrying.

    Returns:
        The plan. It is always internally consistent: exactly one uplink is
        active per line, at most one line is active under failover, and a
        backup-only uplink is active only when nothing else can carry.
    """
    uplinks = network.wan_interfaces
    if not uplinks:
        return UplinkPlan()

    order = _rank_order(uplinks, facts)
    groups = _group_by_line(uplinks, facts, order)
    is_balancing = network.uplink_policy == ROUTER_POLICY_BALANCE
    active_ids = _choose_active_lines(groups, facts, uplinks, is_balancing)

    plan = UplinkPlan()
    rank = 0
    for group in groups:
        line = UpstreamLine(id=group.id, gateway=group.gateway)
        for position, name in enumerate(group.members):
            rank += 1
            interface = _find(uplinks, name)
            entry = facts.get(name, UplinkFacts(name=name))
            is_active = group.id in active_ids and position == 0
            planned = PlannedUplink(
                name=name,
                line_id=group.id,
                rank=rank,
                is_active=is_active,
                route_metric=_metric(interface, rank, is_active),
                reason=_reason(
                    interface=interface,
                    facts=entry,
                    best_of_line=group.members[0],
                    position=position,
                    is_active=is_active,
                ),
                facts=entry,
            )
            line.members.append(planned)
            plan.uplinks.append(planned)
        plan.lines.append(line)
    return plan


@dataclass
class _LineGroup:
    """Uplinks found to share one upstream, before they are ranked into a plan."""

    id: str
    gateway: str | None
    members: list[str]


def _rank_order(
    uplinks: list[RouterInterface], facts: dict[str, UplinkFacts]
) -> dict[str, int]:
    ordered = sorted(
        (interface.name for interface in uplinks),
        key=lambda name: _rank_key(name, uplinks, facts),
    )
    return {name: index for index, name in enumerate(ordered)}


def _group_by_line(
    uplinks: list[RouterInterface],
    facts: dict[str, UplinkFacts],
    order: dict[str, int],
) -> list[_LineGroup]:
    """Put uplinks that reach the same upstream into one group.

    A shared next hop is conclusive: two interfaces handed the same gateway are
    two doors onto one line. Failing that — a link with an address but no route
    yet — overlapping subnets mean the same segment, which on a home or campus
    network means the same line again.

    Args:
        uplinks: The interfaces holding the WAN role.
        facts: What the system says about each.
        order: Each uplink's rank position, used to sort within and between
            groups so the best member leads.

    Returns:
        The groups, best first, each with its members best first.
    """
    groups: list[_LineGroup] = []
    for interface in uplinks:
        entry = facts.get(interface.name, UplinkFacts(name=interface.name))
        group = _matching_group(entry, groups)
        if group is None:
            groups.append(
                _LineGroup(
                    id=_line_id(entry), gateway=entry.gateway, members=[entry.name]
                )
            )
            continue
        group.members.append(entry.name)
        group.gateway = group.gateway or entry.gateway

    for group in groups:
        group.members.sort(key=lambda name: order[name])
    groups.sort(key=lambda group: order[group.members[0]])
    return groups


def _matching_group(entry: UplinkFacts, groups: list[_LineGroup]) -> _LineGroup | None:
    subnet = _subnet(entry.cidr)
    for group in groups:
        if entry.gateway and group.gateway == entry.gateway:
            return group
        if subnet is not None and group.id.startswith("net:"):
            if _overlaps(group.id[4:], subnet):
                return group
    return None


def _line_id(entry: UplinkFacts) -> str:
    if entry.gateway:
        return f"gw:{entry.gateway}"
    subnet = _subnet(entry.cidr)
    if subnet is not None:
        return f"net:{subnet}"
    return f"if:{entry.name}"


def _overlaps(text: str, subnet) -> bool:
    try:
        return ipaddress.ip_network(text, strict=False).overlaps(subnet)
    except ValueError:
        return False


def _subnet(cidr: str | None):
    if not cidr:
        return None
    try:
        return ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None


def _choose_active_lines(
    groups: list[_LineGroup],
    facts: dict[str, UplinkFacts],
    uplinks: list[RouterInterface],
    is_balancing: bool,
) -> set[str]:
    """Pick the lines that should carry traffic.

    Backup-only uplinks are held back until no ordinary one can carry, which is
    the whole point of marking a metered link that way: it may well be the
    fastest thing in the box and must still stay dark.

    Args:
        groups: The upstream lines, best first.
        facts: What the system says about each interface.
        uplinks: The interfaces holding the WAN role.
        is_balancing: Whether the policy is to spread across lines.

    Returns:
        The ids of the lines that should carry traffic.
    """

    def is_usable(group: _LineGroup) -> bool:
        name = group.members[0]
        return facts.get(name, UplinkFacts(name=name)).is_carrying

    def is_ordinary(group: _LineGroup) -> bool:
        return not _find(uplinks, group.members[0]).wan.is_backup_only

    ordinary = [group for group in groups if is_usable(group) and is_ordinary(group)]
    if not ordinary:
        # Nothing ordinary is carrying, so the backups earn their keep. Only
        # the best one: a fallback that balanced across metered links would be
        # a surprising way to spend someone's data.
        fallback = [group for group in groups if is_usable(group)]
        return {fallback[0].id} if fallback else set()
    if is_balancing:
        return {group.id for group in ordinary}
    return {ordinary[0].id}


def _rank_key(
    name: str, uplinks: list[RouterInterface], facts: dict[str, UplinkFacts]
) -> tuple:
    interface = _find(uplinks, name)
    entry = facts.get(name, UplinkFacts(name=name))
    return (
        not entry.is_carrying,
        interface.wan.is_backup_only,
        not interface.wan.is_pinned_primary,
        entry.medium != MEDIUM_WIRED,
        -(entry.speed_mbps or 0),
        [interface.name for interface in uplinks].index(name),
    )


def _metric(interface: RouterInterface, rank: int, is_active: bool) -> int:
    if interface.wan.is_backup_only:
        return ROUTER_METRIC_BACKUP + rank * METRIC_STEP
    return ROUTER_METRIC_BALANCE + (0 if is_active else rank * METRIC_STEP)


def _reason(
    *,
    interface: RouterInterface,
    facts: UplinkFacts,
    best_of_line: str,
    position: int,
    is_active: bool,
) -> str:
    if not facts.is_carrying:
        return "no carrier"
    if position > 0:
        return f"shares an upstream line with {best_of_line}"
    if interface.wan.is_backup_only and not is_active:
        return "held back as backup only"
    if interface.wan.is_backup_only:
        return "backup only, and nothing else is carrying"
    parts = ["wired" if facts.medium == MEDIUM_WIRED else "wireless"]
    if facts.speed_mbps:
        parts.append(f"{_readable_speed(facts.speed_mbps)} link")
    if interface.wan.is_pinned_primary:
        parts.append("pinned primary")
    return ", ".join(parts)


def _readable_speed(mbps: int) -> str:
    if mbps >= 1000 and mbps % 1000 == 0:
        return f"{mbps // 1000} Gb/s"
    if mbps >= 1000:
        return f"{mbps / 1000:g} Gb/s"
    return f"{mbps} Mb/s"


def _find(uplinks: list[RouterInterface], name: str) -> RouterInterface:
    for interface in uplinks:
        if interface.name == name:
            return interface
    raise KeyError(name)
