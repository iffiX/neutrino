"""Reading the live byte counters of this machine's own interfaces.

The long-term view of the same traffic comes from vnstat
(:mod:`neutrino_hub.system.vnstat_history`); this is the reading between two
ticks. It is taken straight out of ``/proc`` rather than by running ``ip``,
because the dashboard asks for it once a second for every open panel and a
subprocess per frame is a cost this number does not carry.
"""

from pathlib import Path

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig

PROC_NET_DEV = Path("/proc/net/dev")
PROC_NET_ROUTE = Path("/proc/net/route")

# Both tables are big-endian hex words. A default route is the one whose
# destination matches everything.
ROUTE_DEFAULT_DESTINATION = "00000000"

# Field offsets after the interface name in /proc/net/dev, whose columns are
# the receive block first and the transmit block second.
DEV_RECEIVED_BYTES_FIELD = 0
DEV_SENT_BYTES_FIELD = 8

# Columns of /proc/net/route.
ROUTE_INTERFACE_FIELD = 0
ROUTE_DESTINATION_FIELD = 1
ROUTE_METRIC_FIELD = 6


def interface_counters(name: str) -> tuple[int, int] | None:
    """Total bytes an interface has received and sent since it came up.

    Args:
        name: Kernel interface name.

    Returns:
        ``(received_bytes, sent_bytes)``, or None when the interface has no
        line in the table — it was renamed, removed, or never existed. None
        rather than zeros, so a caller rating two samples can tell a missing
        interface from an idle one.
    """
    if not name:
        return None
    try:
        table = PROC_NET_DEV.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in table.splitlines():
        label, separator, counters = line.partition(":")
        if not separator or label.strip() != name:
            continue
        fields = counters.split()
        if len(fields) <= DEV_SENT_BYTES_FIELD:
            return None
        try:
            return (
                int(fields[DEV_RECEIVED_BYTES_FIELD]),
                int(fields[DEV_SENT_BYTES_FIELD]),
            )
        except ValueError:
            return None
    return None


def default_route_interface() -> str:
    """The interface this machine's way out currently runs over.

    Returns:
        The device carrying the default route, lowest metric first the way the
        kernel picks it. Empty when the box has no default route at all.
    """
    try:
        table = PROC_NET_ROUTE.read_text(encoding="utf-8")
    except OSError:
        return ""
    routes: list[tuple[int, str]] = []
    for line in table.splitlines()[1:]:
        fields = line.split()
        if len(fields) <= ROUTE_METRIC_FIELD:
            continue
        if fields[ROUTE_DESTINATION_FIELD].upper() != ROUTE_DEFAULT_DESTINATION:
            continue
        metric = fields[ROUTE_METRIC_FIELD]
        routes.append(
            (int(metric) if metric.isdigit() else 0, fields[ROUTE_INTERFACE_FIELD])
        )
    if not routes:
        return ""
    return min(routes)[1]


def traffic_interface(*, network: RouterNetworkConfig) -> str:
    """Which interface's counters are this machine's traffic.

    The configured uplink is the answer wherever there is one, so the reading
    matches the interface the history chart is drawn from. The modes that give
    no port the WAN role still have a way out, and there it is whatever the
    default route runs over.

    Args:
        network: The parsed router configuration.

    Returns:
        A kernel interface name, or empty when the box has neither an uplink
        nor a default route.
    """
    uplinks = network.wan_device_names
    if uplinks:
        return uplinks[0]
    return default_route_interface()
