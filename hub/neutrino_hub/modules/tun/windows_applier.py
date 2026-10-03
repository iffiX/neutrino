"""Bringing the TUN plan up on Windows and taking it down again.

One script gives the wintun adapter tun2socks opened its address with
``New-NetIPAddress``, turns forwarding on with ``Set-NetIPInterface`` for
the interfaces the plan forwards for, and adds each route in the plan's
order with ``New-NetRoute``, all in the active store so a reboot keeps
none of it. Another removes each recorded route in reverse with
``Remove-NetRoute`` and turns forwarding off again where the hub turned it
on.

Not pure: runs PowerShell.
"""

from neutrino_hub.modules.tun.applied_state import TunAppliedState
from neutrino_hub.modules.tun.constants import (
    TUN_WINDOWS_DOWN_SCRIPT,
    TUN_WINDOWS_UP_SCRIPT,
)
from neutrino_hub.modules.tun.renderer import TunPlan, windows_route_document
from neutrino_hub.system.powershell_run import listed, run_powershell


class TunWindowsApplier:
    """Drives the wintun adapter's address, forwarding and routes."""

    def __init__(self, *, powershell=None):
        """
        Args:
            powershell: Runs one script with a document, as
                :func:`neutrino_hub.system.powershell_run.run_powershell`
                does; None is that function.
        """
        self._powershell = powershell if powershell is not None else run_powershell

    def bring_up(self, plan: TunPlan, *, keep=None) -> TunAppliedState:
        """Give the adapter its address, turn forwarding on, add the routes.

        Args:
            plan: The plan.
            keep: Called with the state once the script answered; None keeps
                nothing.

        Returns:
            What was applied. A route the script could not add is recorded
            as a failure.

        Raises:
            OSError: When PowerShell cannot run or the address or forwarding
                is refused.
        """
        answer = self._powershell(
            TUN_WINDOWS_UP_SCRIPT,
            {
                "alias": plan.device,
                "address": plan.address,
                "prefix_length": plan.prefix_length,
                "forwarding": list(plan.forwarding_devices),
                "routes": [windows_route_document(route) for route in plan.routes],
            },
        )
        added = {str(prefix) for prefix in listed(answer.get("added"))}
        state = TunAppliedState(
            plan=plan.to_dict(),
            routes=[route for route in plan.routes if route.destination in added],
            forwarded_devices=[str(name) for name in listed(answer.get("forwarded"))],
            failures=[
                f"{entry.get('prefix', '')}: {entry.get('detail', '')}"
                for entry in listed(answer.get("failed"))
                if isinstance(entry, dict)
            ],
        )
        if keep is not None:
            keep(state)
        return state

    def withdraw(self, state: TunAppliedState) -> list:
        """Remove every recorded route in reverse and turn forwarding back off.

        Args:
            state: What a bring-up applied.

        Returns:
            One line per route removed and one per interface whose
            forwarding was turned off.

        Raises:
            OSError: When PowerShell cannot run.
        """
        if not state.routes and not state.forwarded_devices:
            return []
        self._powershell(
            TUN_WINDOWS_DOWN_SCRIPT,
            {
                "routes": [
                    windows_route_document(route) for route in reversed(state.routes)
                ],
                "forwarding": list(state.forwarded_devices),
            },
        )
        return [
            f"route {route.destination} withdrawn" for route in reversed(state.routes)
        ] + [f"forwarding off on {name}" for name in state.forwarded_devices]
