"""Running the lease client on one uplink, and reading the lease it holds.

One unit per uplink, because what differs between two of them is the route
metric — which is how the gateway decides which one traffic actually leaves by
— and that lives in each one's rendered configuration.

Not pure: talks to systemd and runs dhcpcd.
"""

import ipaddress
import os
import shutil
import subprocess

from neutrino_hub.modules.router.constants import (
    ROUTER_DHCP_BINARIES,
    ROUTER_DHCP_LEASE_DIR,
    ROUTER_DHCP_LEASE_SUFFIX,
    ROUTER_DHCP_MAGIC_COOKIE,
    ROUTER_DHCP_OPTION_DNS,
    ROUTER_DHCP_OPTION_END,
    ROUTER_DHCP_OPTION_PAD,
    ROUTER_DHCP_OPTIONS_OFFSET,
    ROUTER_DHCP_UNIT,
    ROUTER_LEASE_DNS_KEY,
    ROUTER_LEASE_READ_TIMEOUT_S,
    router_dhcp_config_path,
)
from neutrino_hub.system.systemd_ctl import unit_state
from neutrino_hub.utils.subprocess_run import run


class RouterDhcpClient:
    """Starts and stops the lease client on one interface.

    Asked for, never waited on. This unit is ordered `After=` the router unit
    and the applier that starts it runs inside that unit, so `--now` would
    have the router wait for something systemd will not start until the router
    has finished — a deadlock broken only by a job timeout, with everything
    ordered behind the router stuck for as long as it lasts.
    """

    def __init__(self, *, interface: str):
        """
        Args:
            interface: The uplink's interface name.
        """
        self._interface = interface

    @property
    def unit(self) -> str:
        """The systemd unit running the client on this interface."""
        return ROUTER_DHCP_UNIT.format(interface=self._interface)

    @property
    def is_running(self) -> bool:
        """Whether the client is up on this interface."""
        return run(
            ["systemctl", "is-active", "--quiet", self.unit], is_checked=False
        ).is_success

    @property
    def state(self) -> str:
        """What systemd says this client's unit is doing now."""
        return unit_state(self.unit)

    def lease_dns(self) -> list[str]:
        """The resolvers the lease on this interface names.

        Read from the lease file dhcpcd keeps; where there is none, from
        ``dhcpcd --dumplease``, which asks the running client.

        Returns:
            The addresses in the lease's order; empty when there is no lease
            file and dhcpcd is not installed, holds no lease here, or does
            not answer in time.
        """
        path = ROUTER_DHCP_LEASE_DIR / f"{self._interface}{ROUTER_DHCP_LEASE_SUFFIX}"
        try:
            return lease_file_dns(path.read_bytes())
        except OSError:
            pass
        binary = next(
            (path for path in ROUTER_DHCP_BINARIES if os.path.isfile(path)), None
        ) or shutil.which("dhcpcd")
        if binary is None:
            return []
        command = [binary, "--dumplease", "-4"]
        config = router_dhcp_config_path(self._interface)
        if config.is_file():
            command += ["--config", str(config)]
        command.append(self._interface)
        try:
            result = run(
                command, is_checked=False, timeout_s=ROUTER_LEASE_READ_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            return []
        if not result.is_success:
            return []
        return parse_lease_dns(result.stdout)

    def start(self) -> None:
        """Ask for the client, and keep it started across reboots."""
        run(["systemctl", "enable", self.unit], is_checked=False)
        run(["systemctl", "start", "--no-block", self.unit], is_checked=False)

    def restart(self) -> None:
        """Have the client read its configuration afresh.

        Used when the metric changed: the route it installs carries it, and
        the running client will not move a route it has already put down.
        """
        run(["systemctl", "enable", self.unit], is_checked=False)
        run(["systemctl", "restart", "--no-block", self.unit], is_checked=False)

    def stop(self) -> None:
        """Stop the client and stop it coming back.

        The address it fetched stays: `persistent` in the rendered
        configuration is what keeps a reconfiguration from dropping the link
        the panel is answering on.
        """
        run(["systemctl", "disable", "--now", self.unit], is_checked=False)


def lease_file_dns(data: bytes) -> list[str]:
    """The resolvers in a lease file dhcpcd wrote.

    Args:
        data: The file: the DHCP message the lease came in, option 6 listing
            the resolvers.

    Returns:
        The IPv4 addresses option 6 lists, in order; empty when the file is
        not a DHCP message or names none.
    """
    if data[ROUTER_DHCP_OPTIONS_OFFSET - 4 : ROUTER_DHCP_OPTIONS_OFFSET] != (
        ROUTER_DHCP_MAGIC_COOKIE
    ):
        return []
    index = ROUTER_DHCP_OPTIONS_OFFSET
    while index < len(data):
        code = data[index]
        if code == ROUTER_DHCP_OPTION_END:
            break
        if code == ROUTER_DHCP_OPTION_PAD:
            index += 1
            continue
        if index + 1 >= len(data):
            break
        length = data[index + 1]
        value = data[index + 2 : index + 2 + length]
        if code == ROUTER_DHCP_OPTION_DNS:
            return [
                str(ipaddress.IPv4Address(value[start : start + 4]))
                for start in range(0, len(value) - len(value) % 4, 4)
            ]
        index += 2 + length
    return []


def parse_lease_dns(text: str) -> list[str]:
    """The resolvers in what ``dhcpcd --dumplease`` printed.

    Args:
        text: The dump, one ``name='value'`` per line; a ``new_`` prefix on
            the name, as dhcpcd's hooks see it, reads the same.

    Returns:
        The IP addresses ``domain_name_servers`` lists, in order; empty when
        the dump names none.
    """
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        name = name.strip().removeprefix("new_")
        if not separator or name != ROUTER_LEASE_DNS_KEY:
            continue
        addresses = []
        for word in value.strip().strip("'\"").split():
            try:
                addresses.append(str(ipaddress.ip_address(word)))
            except ValueError:
                continue
        return addresses
    return []
