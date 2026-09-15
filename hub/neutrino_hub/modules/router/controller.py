"""Making the routing state match `config/`, in one ordered pass.

Every writer of the routing state goes through here: the resident router unit
on each link, address, route or rule event, `nhub apply`, and the panel's
applies. One order and one lock for all of them. Each step stands on its own,
so a step that cannot be done yet waits for the event that allows it, and the
steps after it still run.

Not pure: drives the appliers in :mod:`neutrino_hub.modules.router.routes`.
"""

import contextlib
import fcntl
import os
import subprocess
import time
from pathlib import Path

from neutrino_hub.modules.netbird.ops import NetbirdInboundGate
from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_CODE_POLICY_ROUTE_MISSING,
    ROUTER_LOCK_PATH,
    ROUTER_LOCK_POLL_S,
    ROUTER_LOCK_TIMEOUT_S,
    ROUTER_NETWORK_FILE,
    ROUTER_NFT_DIVERT_MARKER,
    ROUTER_NFT_PATH,
    ROUTER_OVERLAY_NETBIRD,
    ROUTER_ROUTING_FILE,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_UNCHANGED,
    ROUTER_TRIGGER_APPLY,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import admin_up_interfaces
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.routes import (
    RouterInterfaceApplier,
    RouterRulesetApplier,
    lookup_xray_uid,
    served_networks,
)
from neutrino_hub.modules.router.steps import RouterStepResult, run_step
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import command_failure_text


@contextlib.contextmanager
def router_lock(*, path: Path | None = None, timeout_s: float = ROUTER_LOCK_TIMEOUT_S):
    """Hold the one lock every writer of the routing state takes.

    Args:
        path: The lock file; :data:`ROUTER_LOCK_PATH` when None.
        timeout_s: How long to wait for it; 0 tries once.

    Yields:
        Nothing; the lock is held inside the block.

    Raises:
        TimeoutError: When another writer holds it past the timeout.
    """
    path = path or ROUTER_LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"another apply holds {path}")
                time.sleep(ROUTER_LOCK_POLL_S)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class RouterStateController:
    """Drives the kernel's routing state to what `config/` says."""

    def __init__(
        self,
        *,
        trigger: str = ROUTER_TRIGGER_APPLY,
        on_base_ready=None,
        lock_path: Path | None = None,
    ):
        """
        Args:
            trigger: ``apply`` for a person or a command, ``event`` for the
                resident unit. An event leaves an engine systemd is already
                restarting to systemd.
            on_base_ready: Called once the firewall step has been tried,
                before any step that starts a unit ordered after the router
                unit.
            lock_path: The lock file every writer takes; the usual one when
                None.
        """
        self._trigger = trigger
        self._on_base_ready = on_base_ready
        self._lock_path = lock_path

    def reconcile(self, *, only: str | None = None) -> list[RouterStepResult]:
        """Take the lock and run one pass.

        Args:
            only: Limit the interface steps to this interface. Every other
                step runs whatever this is.

        Returns:
            One result per step, in the order they ran.

        Raises:
            TimeoutError: When another writer holds the lock too long.
            ValueError: When ``only`` names no configured interface, or the
                configuration is invalid.
            FileNotFoundError: When the box is not set up.
            RuntimeError: When the proxy core's account does not exist yet.
        """
        with router_lock(path=self._lock_path):
            return self.reconcile_locked(only=only)

    def reconcile_locked(self, *, only: str | None = None) -> list[RouterStepResult]:
        """Run one pass for a caller that already holds the lock.

        Args:
            only: Limit the interface steps to this interface.

        Returns:
            One result per step, in the order they ran.

        Raises:
            ValueError: When ``only`` names no configured interface, or the
                configuration is invalid.
            FileNotFoundError: When the box is not set up.
            RuntimeError: When the proxy core's account does not exist yet.
        """
        network = RouterNetworkConfig.from_dict(read_config(ROUTER_NETWORK_FILE))
        routing = read_config(ROUTER_ROUTING_FILE)
        if only is not None and network.interface(only) is None:
            raise ValueError(f"{only!r} is not a configured interface")
        ruleset = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
        ).render()
        is_diverting = ROUTER_NFT_DIVERT_MARKER in ruleset
        rules = RouterRulesetApplier()

        results = [
            run_step(
                "forwarding",
                lambda: rules.enable_forwarding(
                    is_forwarding=is_forwarding(network), is_diverting=is_diverting
                ),
            )
        ]
        policy = run_step(
            "policy_route",
            rules.ensure_policy_route if is_diverting else rules.remove_policy_route,
        )
        results.append(policy)
        results.append(
            _load_ruleset(rules, ruleset, is_diverting=is_diverting, policy=policy)
        )
        if self._on_base_ready is not None:
            self._on_base_ready()

        results += self._apply_interfaces(network, only)
        if is_diverting:
            results += _sync_served_routes(rules, network)
        results += _converge_overlays(network)
        return results

    def _apply_interfaces(
        self, network: RouterNetworkConfig, only: str | None
    ) -> list[RouterStepResult]:
        """The interface roles, the default route and the resolver.

        Args:
            network: The parsed router configuration.
            only: Limit the interface steps to this interface.

        Returns:
            One result per step.
        """
        try:
            applier = RouterInterfaceApplier(
                network=network, trigger=self._trigger, is_lease_awaited=False
            )
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            return [
                RouterStepResult(
                    name="interfaces",
                    state=ROUTER_STEP_FAILED,
                    code=ROUTER_CODE_COMMAND_FAILED,
                    detail=command_failure_text(error),
                )
            ]
        return applier.apply_steps(only)


def is_forwarding(network: RouterNetworkConfig) -> bool:
    """Whether any interface holds a role that routes.

    Args:
        network: The parsed router configuration.

    Returns:
        True when something forwards, which is what earns the forwarding
        sysctls; a box with no roles is somebody's machine and keeps its own.
    """
    return bool(network.lan_interfaces or network.wan_interfaces)


def failure_text(results: list[RouterStepResult]) -> str:
    """The failed steps, as one sentence for a person.

    Args:
        results: What a pass reported.

    Returns:
        Each failed step with its detail, empty when none failed.
    """
    return "; ".join(result.describe() for result in results if result.is_failed)


def _load_ruleset(
    rules: RouterRulesetApplier,
    ruleset: str,
    *,
    is_diverting: bool,
    policy: RouterStepResult,
) -> RouterStepResult:
    """Load the ruleset when it differs from what the kernel holds.

    Args:
        rules: The applier.
        ruleset: The rendered ruleset.
        is_diverting: Whether the ruleset diverts into the proxy.
        policy: The policy route step's result.

    Returns:
        The ruleset step's result.
    """
    is_loaded = rules.is_table_loaded()
    if is_loaded and _loaded_text() == ruleset:
        return RouterStepResult(name="ruleset", state=ROUTER_STEP_UNCHANGED)
    if policy.is_failed and is_diverting and is_loaded:
        # A diverting ruleset with no policy route sends what it diverts
        # nowhere. The previous ruleset stays; with no table at all the new
        # one loads anyway, since a closed firewall beats an open box.
        return RouterStepResult(
            name="ruleset",
            state=ROUTER_STEP_FAILED,
            code=ROUTER_CODE_POLICY_ROUTE_MISSING,
            detail=policy.detail,
        )

    def load() -> list[str]:
        rules.load_ruleset(ruleset)
        # Written after the load: the panel reads this file to say where
        # traffic is going.
        write_generated(ROUTER_NFT_PATH, ruleset)
        return ["ruleset loaded"]

    return run_step("ruleset", load)


def _loaded_text() -> str:
    """The ruleset last loaded, or an empty string when none was."""
    try:
        return ROUTER_NFT_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _sync_served_routes(
    rules: RouterRulesetApplier, network: RouterNetworkConfig
) -> list[RouterStepResult]:
    """One route per served network in the policy table.

    Args:
        rules: The applier.
        network: The parsed router configuration.

    Returns:
        One result per served network, and one per stale route removed.
    """
    try:
        admin_up = admin_up_interfaces()
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        return [
            RouterStepResult(
                name="served_route",
                state=ROUTER_STEP_FAILED,
                code=ROUTER_CODE_COMMAND_FAILED,
                detail=command_failure_text(error),
            )
        ]
    return rules.sync_served_routes(served_networks(network), admin_up=admin_up)


def _converge_overlays(network: RouterNetworkConfig) -> list[RouterStepResult]:
    """Tell each overlay's own daemon what the exposure switch says.

    NetBird's client puts an accept for its interface back into the input
    chain within seconds of a reload, so the switch reaches its own setting
    too. The gate is a no-op when the daemon already agrees.

    Args:
        network: The parsed router configuration.

    Returns:
        One result per NetBird overlay.
    """
    results = []
    for overlay in network.overlays:
        if overlay.provider != ROUTER_OVERLAY_NETBIRD:
            continue

        def converge(overlay=overlay) -> list[str]:
            note = NetbirdInboundGate().converge(is_blocked=not overlay.is_exposed)
            return [note] if note else []

        results.append(run_step(f"overlay_gate {overlay.title}", converge))
    return results
