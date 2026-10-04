"""What the service applied of a TUN plan, kept so it can be withdrawn exactly.

Every route added, in the order it was added, the forwarding turned on and
what it was before, the routes that could not be added, and the plan they
came from. A restart or a stop of the service reads this back and takes away
what it names and nothing else.

Not pure: reads and writes the state file.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from neutrino_hub.modules.tun.renderer import TunRoute
from neutrino_hub.utils.json_file import write_generated


@dataclass
class TunAppliedState:
    """The routes and forwarding one bring-up left on the machine.

    Attributes:
        plan: The plan applied, as :meth:`TunPlan.to_dict` wrote it.
        routes: Each route added, in the order it was added.
        forwarding_before: On macOS, what ``net.inet.ip.forwarding`` read
            before the hub turned it on; empty when the hub did not.
        forwarded_devices: On Windows, the interfaces the hub turned
            forwarding on for.
        failures: One line per route or step that could not be done.
        endpoints: The destinations among ``routes`` the keeper added for
            the overlay engines' endpoints after the bring-up.
    """

    plan: dict = field(default_factory=dict)
    routes: list = field(default_factory=list)
    forwarding_before: str = ""
    forwarded_devices: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    endpoints: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """The state as the file keeps it.

        Returns:
            Every attribute, the routes as dicts.
        """
        return {
            "plan": self.plan,
            "routes": [route.to_dict() for route in self.routes],
            "forwarding_before": self.forwarding_before,
            "forwarded_devices": list(self.forwarded_devices),
            "failures": list(self.failures),
            "endpoints": list(self.endpoints),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TunAppliedState":
        """Read the state back; an entry it cannot read is left out.

        Args:
            data: What :meth:`to_dict` wrote.

        Returns:
            The state.
        """
        routes = []
        for entry in data.get("routes") or []:
            try:
                routes.append(TunRoute.from_dict(entry))
            except (KeyError, TypeError, AttributeError):
                continue
        plan = data.get("plan")
        return cls(
            plan=plan if isinstance(plan, dict) else {},
            routes=routes,
            forwarding_before=str(data.get("forwarding_before") or ""),
            forwarded_devices=[
                str(name) for name in data.get("forwarded_devices") or []
            ],
            failures=[str(line) for line in data.get("failures") or []],
            endpoints=[str(line) for line in data.get("endpoints") or []],
        )


def read_applied(path: Path) -> "TunAppliedState | None":
    """The state kept at a path.

    Args:
        path: The state file.

    Returns:
        The state, or None when nothing is kept or it cannot be read.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return TunAppliedState.from_dict(data)


def write_applied(path: Path, state: TunAppliedState) -> None:
    """Keep the state, readable by root alone.

    Args:
        path: The state file.
        state: What was applied.

    Raises:
        OSError: When the file cannot be written.
    """
    write_generated(path, json.dumps(state.to_dict(), indent=2) + "\n", mode=0o600)


def forget_applied(path: Path) -> None:
    """Delete the kept state.

    Args:
        path: The state file.

    Raises:
        OSError: When the file is there and cannot be deleted.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return
