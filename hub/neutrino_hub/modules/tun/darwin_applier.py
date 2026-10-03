"""Bringing the TUN plan up on macOS and taking it down again.

``ifconfig`` gives the utun device tun2socks opened its address, ``sysctl``
turns IP forwarding on when the plan forwards for the overlays, and
``route add`` adds each route in the plan's order. Taking it down deletes
each recorded route in reverse with ``route delete`` and sets forwarding
back to what it read before. A route onto the device that went away with it
is already gone, which is not an error.

Not pure: runs ``ifconfig``, ``sysctl`` and ``route``.
"""

from neutrino_hub.modules.tun.applied_state import TunAppliedState
from neutrino_hub.modules.tun.constants import TUN_DARWIN_FORWARDING_KEY
from neutrino_hub.modules.tun.renderer import (
    TunPlan,
    darwin_address_command,
    darwin_route_command,
)
from neutrino_hub.utils.subprocess_run import run as run_command


class TunDarwinApplier:
    """Drives the utun device's address, forwarding and routes."""

    def __init__(self, *, run=None):
        """
        Args:
            run: Runs one command, as
                :func:`neutrino_hub.utils.subprocess_run.run` does; None is
                that function.
        """
        self._run = run if run is not None else run_command

    def bring_up(self, plan: TunPlan, *, keep=None) -> TunAppliedState:
        """Give the device its address, turn forwarding on, add the routes.

        A route that cannot be added is recorded as a failure and the rest
        are still tried. Nothing is added when the device takes no address.

        Args:
            plan: The plan.
            keep: Called with the state after each change, so a stop in the
                middle still knows what was added; None keeps nothing.

        Returns:
            What was applied.
        """
        state = TunAppliedState(plan=plan.to_dict())
        address = self._run(darwin_address_command(plan), is_checked=False)
        if not address.is_success:
            state.failures.append(_failure(address))
            return state
        if plan.forwarding_devices:
            before = self._run(
                ["sysctl", "-n", TUN_DARWIN_FORWARDING_KEY], is_checked=False
            )
            value = before.stdout.strip() if before.is_success else ""
            if value != "1":
                turned = self._run(
                    ["sysctl", "-w", f"{TUN_DARWIN_FORWARDING_KEY}=1"],
                    is_checked=False,
                )
                if turned.is_success:
                    state.forwarding_before = value or "0"
                else:
                    state.failures.append(_failure(turned))
                _keep(keep, state)
        for route in plan.routes:
            added = self._run(darwin_route_command("add", route), is_checked=False)
            if not added.is_success:
                state.failures.append(_failure(added))
                continue
            state.routes.append(route)
            _keep(keep, state)
        return state

    def withdraw(self, state: TunAppliedState) -> list:
        """Delete every recorded route in reverse and set forwarding back.

        Args:
            state: What a bring-up applied.

        Returns:
            One line per route deleted and one when forwarding was set back.
        """
        notes = []
        for route in reversed(state.routes):
            deleted = self._run(darwin_route_command("delete", route), is_checked=False)
            if deleted.is_success:
                notes.append(f"route {route.destination} withdrawn")
        if state.forwarding_before:
            self._run(
                [
                    "sysctl",
                    "-w",
                    f"{TUN_DARWIN_FORWARDING_KEY}={state.forwarding_before}",
                ],
                is_checked=False,
            )
            notes.append("forwarding set back")
        return notes


def _keep(keep, state: TunAppliedState) -> None:
    """Hand the state to the keeper, when there is one."""
    if keep is not None:
        keep(state)


def _failure(result) -> str:
    """One line naming a refused command and what it said."""
    words = (result.stderr or result.stdout or "").strip()
    return f"{' '.join(result.command)}: {words or f'exit {result.exit_code}'}"
