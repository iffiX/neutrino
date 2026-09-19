"""Reading counters out of the running xray, and moving its override.

The ``xray api`` command-line client is used rather than generated gRPC stubs:
the panel polls a handful of counters every couple of seconds, and shelling out
keeps the repo free of protobuf build steps.

Nothing here logs what a command printed. ``lso`` prints every outbound in
full, node passwords and user ids included.
"""

import json
from dataclasses import dataclass

from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.xray.constants import (
    XRAY_API_LISTEN,
    XRAY_API_PORT,
    XRAY_BALANCER_TAG,
    XRAY_BINARY,
)

API_TIMEOUT_S = 10
# The line `xray api bi` prints the override on. It has no JSON mode.
OVERRIDE_LABEL = "Selecting Override"


@dataclass
class OutboundTraffic:
    """Cumulative byte counters for one outbound.

    Attributes:
        tag: Outbound tag, for example ``node_hk1``.
        uplink_bytes: Bytes sent through it since xray started.
        downlink_bytes: Bytes received through it since xray started.
    """

    tag: str
    uplink_bytes: int
    downlink_bytes: int


class XrayStatsClient:
    """Queries the xray statistics and observatory APIs."""

    def __init__(self, *, server: str | None = None):
        """
        Args:
            server: ``host:port`` of the API inbound. Defaults to the loopback
                endpoint the renderer configures.
        """
        self._server = server or f"{XRAY_API_LISTEN}:{XRAY_API_PORT}"

    def outbound_traffic(self) -> list[OutboundTraffic]:
        """Read per-outbound byte counters.

        Returns:
            One entry per outbound that has moved traffic, node outbounds and
            the direct outbound alike. Empty when xray is not reachable.
        """
        statistics = self._query_stats()
        totals: dict[str, dict[str, int]] = {}
        for name, value in statistics.items():
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "outbound":
                continue
            tag, direction = parts[1], parts[3]
            totals.setdefault(tag, {"uplink": 0, "downlink": 0})[direction] = value
        return [
            OutboundTraffic(
                tag=tag,
                uplink_bytes=counters.get("uplink", 0),
                downlink_bytes=counters.get("downlink", 0),
            )
            for tag, counters in sorted(totals.items())
        ]

    def override_target(self) -> str:
        """Read which outbound the balancer's override names.

        Returns:
            The tag, empty when xray holds no override. Empty with a tag in
            the store is an xray that restarted.

        Raises:
            ConnectionError: If ``xray api`` could not be run or exited
                non-zero.
        """
        return _parse_override(self._api("bi", XRAY_BALANCER_TAG))

    def set_override(self, tag: str) -> None:
        """Make the balancer answer with one outbound until told otherwise.

        The outbound does not have to be in the balancer's selector: ``direct``
        is accepted, and traffic then leaves directly.

        Args:
            tag: The outbound tag.

        Raises:
            ConnectionError: If ``xray api`` could not be run or exited
                non-zero.
        """
        self._api("bo", "-b", XRAY_BALANCER_TAG, tag)

    def clear_override(self) -> None:
        """Hand the balancer back its own choice.

        Raises:
            ConnectionError: If ``xray api`` could not be run or exited
                non-zero.
        """
        self._api("bo", "-b", XRAY_BALANCER_TAG, "-r")

    def inbound_tags(self) -> list[str]:
        """Read which inbounds the running xray carries.

        Returns:
            One tag per inbound.

        Raises:
            ConnectionError: If ``xray api`` could not be run, exited
                non-zero, or printed something that is not its own JSON.
        """
        return _tags_in(self._api("lsi"))

    def outbound_tags(self) -> list[str]:
        """Read which outbounds the running xray carries.

        Returns:
            One tag per outbound.

        Raises:
            ConnectionError: If ``xray api`` could not be run, exited
                non-zero, or printed something that is not its own JSON.
        """
        return _tags_in(self._api("lso"))

    def _api(self, verb: str, *arguments: str) -> str:
        """Run one `xray api` verb and hand back what it printed.

        Args:
            verb: The subcommand, for example ``bi``.
            arguments: What follows the server flag.

        Returns:
            Its standard output.

        Raises:
            ConnectionError: If the command could not be run or exited
                non-zero. The message carries the verb, the exit status and
                the command's standard error; never its standard output.
        """
        result = run(
            [XRAY_BINARY, "api", verb, f"--server={self._server}", *arguments],
            is_checked=False,
            timeout_s=API_TIMEOUT_S,
        )
        if not result.is_success:
            reason = result.stderr.strip() or "it printed no reason"
            raise ConnectionError(
                f"xray api {verb} exited {result.exit_code}: {reason}"
            )
        return result.stdout

    def _query_stats(self) -> dict[str, int]:
        result = run(
            [XRAY_BINARY, "api", "statsquery", f"--server={self._server}"],
            is_checked=False,
            timeout_s=API_TIMEOUT_S,
        )
        if not result.is_success or not result.stdout.strip():
            return {}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}
        return {
            entry["name"]: int(entry.get("value", 0))
            for entry in payload.get("stat", [])
            if "name" in entry
        }


def _parse_override(output: str) -> str:
    """The outbound tag an `xray api bi` answer names as the override.

    The label sits on a line of its own and the value on the row under it.

    Args:
        output: What the command printed.

    Returns:
        The tag, empty when the answer names none.
    """
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if OVERRIDE_LABEL not in line:
            continue
        for following in lines[index + 1 :]:
            row = following.strip()
            if not row:
                continue
            if row.startswith("- "):
                break
            return _row_value(row)
        return ""
    return ""


def _row_value(row: str) -> str:
    """The value of one row `xray api bi` printed.

    A row is an index, the value, and spaces to a fixed width. A row carrying
    no value is the index by itself, so the last field on the line is the
    index rather than a tag.

    Args:
        row: The row, its padding already stripped.

    Returns:
        The value, empty when the row carries none.
    """
    fields = row.split()
    if len(fields) < 2:
        return ""
    return fields[1]


def _tags_in(output: str) -> list[str]:
    """Every tag an `xray api lsi` or `lso` answer carries.

    Args:
        output: What the command printed.

    Returns:
        The tags, in the order they appear.

    Raises:
        ConnectionError: If the answer is not JSON. The answer itself is never
            carried into the message: `lso` prints the node secrets in it.
    """
    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as error:
        raise ConnectionError(
            f"xray printed an answer that is not JSON: {error}"
        ) from error
    return [
        entry["tag"]
        for entry in _listed(payload)
        if isinstance(entry, dict) and isinstance(entry.get("tag"), str)
    ]


def _listed(payload) -> list:
    """The array of handlers in a parsed `lsi` or `lso` answer."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for value in payload.values():
        if isinstance(value, list):
            return value
    return []
