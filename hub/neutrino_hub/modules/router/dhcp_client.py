"""Running the lease client on one uplink.

One unit per uplink, because what differs between two of them is the route
metric — which is how the gateway decides which one traffic actually leaves by
— and that lives in each one's rendered configuration.

Not pure: talks to systemd.
"""

from neutrino_hub.modules.router.constants import ROUTER_DHCP_UNIT
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
