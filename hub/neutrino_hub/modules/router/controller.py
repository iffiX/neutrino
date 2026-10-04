"""Making the routing state match `config/`, in one ordered pass.

Every writer of the routing state goes through here: the resident router unit
on each link, address, route or rule event, `nhub apply`, and the panel's
applies. One order and one lock for all of them. Each step stands on its own,
so a step that cannot be done yet waits for the event that allows it, and the
steps after it still run.

Not pure: drives the appliers in :mod:`neutrino_hub.modules.router.routes`.
On macOS and Windows the pass drives the system firewall and the TUN
device's plan instead, and touches no nftables table.
"""

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

from neutrino_hub.modules.firewall.ops import converge_firewall
from neutrino_hub.modules.netbird.ops import NetbirdInboundGate
from neutrino_hub.modules.overlay.ops import overlay_devices
from neutrino_hub.modules.tun.constants import TUN_CODE_ROUTE_FAILED, TUN_STEP_NAME
from neutrino_hub.modules.tun.ops import converge_tun
from neutrino_hub.platforms.detect import hub_platform, is_linux
from neutrino_hub.modules.router.constants import (
    ROUTER_CGROUP_ROOT,
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_CODE_NETWORK_CHANGED,
    ROUTER_CODE_POLICY_ROUTE_MISSING,
    ROUTER_ENGINE_CGROUPS_PATH,
    ROUTER_ENGINE_UNITS,
    ROUTER_LOCK_PATH,
    ROUTER_LOCK_POLL_S,
    ROUTER_LOCK_TIMEOUT_S,
    ROUTER_NETWORK_FILE,
    ROUTER_NFT_DIVERT_MARKER,
    ROUTER_NFT_PATH,
    ROUTER_OVERLAY_DEVICES_PATH,
    ROUTER_OVERLAY_NETBIRD,
    ROUTER_ROUTING_FILE,
    ROUTER_SERVICE_SLICE,
    ROUTER_STEP_CHANGE_CODES,
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
    platform = hub_platform()
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while not platform.try_lock(descriptor):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"another apply holds {path}")
            time.sleep(ROUTER_LOCK_POLL_S)
        try:
            yield
        finally:
            platform.unlock(descriptor)
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
        if not is_linux():
            return self._reconcile_firewall(network, routing)
        devices = overlay_devices(network)
        cgroups = engine_cgroups(routing)
        ruleset = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
            overlay_devices=devices,
            engine_cgroups=list(cgroups),
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
        loaded = _load_ruleset(
            rules,
            ruleset,
            is_diverting=is_diverting,
            policy=policy,
            is_cgroup_moved=cgroups != rendered_engine_cgroups(),
        )
        results.append(loaded)
        if not loaded.is_failed:
            write_generated(ROUTER_OVERLAY_DEVICES_PATH, json.dumps(devices))
            write_generated(ROUTER_ENGINE_CGROUPS_PATH, json.dumps(cgroups))
        if self._on_base_ready is not None:
            self._on_base_ready()

        results += self._apply_interfaces(network, only)
        if is_diverting:
            results += _sync_served_routes(rules, network)
        results += _converge_overlays(network)
        return results

    def _reconcile_firewall(
        self, network: RouterNetworkConfig, routing: dict
    ) -> list[RouterStepResult]:
        """The pass on macOS and Windows: the firewall, the TUN and the overlays."""
        devices = overlay_devices(network)
        found = network.with_overlay_devices(devices)
        refused = []

        def firewall() -> list:
            notes, failed = converge_firewall(found, routing=routing)
            refused.extend(failed)
            return notes

        results = [run_step("firewall", firewall)]
        results += [
            RouterStepResult(
                name=f"firewall {entry['rule']}",
                state=ROUTER_STEP_FAILED,
                code=ROUTER_CODE_COMMAND_FAILED,
                detail=entry["detail"],
            )
            for entry in refused
        ]
        tun = run_step(TUN_STEP_NAME, lambda: converge_tun(found, routing))
        if tun.is_failed:
            tun = RouterStepResult(
                name=tun.name,
                state=tun.state,
                code=TUN_CODE_ROUTE_FAILED,
                detail=tun.detail,
            )
        results.append(tun)
        write_generated(ROUTER_OVERLAY_DEVICES_PATH, json.dumps(devices))
        if self._on_base_ready is not None:
            self._on_base_ready()
        return results + _converge_overlays(network)

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


def rendered_overlay_devices() -> dict:
    """The overlay devices found at run time that the loaded ruleset names.

    Returns:
        Provider to device names, as
        :func:`neutrino_hub.modules.overlay.ops.overlay_devices` found them
        for the last ruleset loaded; empty when none was recorded.
    """
    try:
        stored = json.loads(ROUTER_OVERLAY_DEVICES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {
        str(provider): [str(name) for name in names]
        for provider, names in stored.items()
        if isinstance(names, list)
    }


def engine_cgroups(routing: dict, *, root: Path = ROUTER_CGROUP_ROOT) -> dict:
    """The overlay engines' cgroups the output chain names, as they are now.

    Args:
        routing: Parsed ``config/xray/routing.json``.
        root: Where the cgroup tree is mounted.

    Returns:
        Each engine cgroup present, as its path under the root, to its id;
        empty while the local proxy is off.
    """
    if not routing.get("is_local_proxy_enabled", False):
        return {}
    found = {}
    for unit in ROUTER_ENGINE_UNITS:
        path = f"{ROUTER_SERVICE_SLICE}/{unit}"
        try:
            found[path] = (root / path).stat().st_ino
        except OSError:
            continue
    return found


def rendered_engine_cgroups() -> dict:
    """The engine cgroups the loaded ruleset names.

    Returns:
        Path to id, as :func:`engine_cgroups` found them for the last
        ruleset loaded; empty when none was recorded.
    """
    try:
        stored = json.loads(ROUTER_ENGINE_CGROUPS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(path): number for path, number in stored.items()}


def failure_text(results: list[RouterStepResult]) -> str:
    """The failed steps, as one sentence for a person.

    Args:
        results: What a pass reported.

    Returns:
        Each failed step with its detail, empty when none failed.
    """
    return "; ".join(result.describe() for result in results if result.is_failed)


def change_codes(results: list[RouterStepResult]) -> list[dict]:
    """The steps that changed something, as codes for the panel.

    Args:
        results: What a pass reported.

    Returns:
        One ``{code, params}`` per step that changed something; ``name`` is
        the interface or overlay the step is about, when it names one.
    """
    codes = []
    for result in results:
        if result.is_failed or not result.changes:
            continue
        kind, _, subject = result.name.partition(" ")
        code = ROUTER_STEP_CHANGE_CODES.get(kind, ROUTER_CODE_NETWORK_CHANGED)
        codes.append({"code": code, "params": {"name": subject} if subject else {}})
    return codes


def failure_codes(results: list[RouterStepResult]) -> list[dict]:
    """The failed steps, as codes for the panel.

    Args:
        results: What a pass reported.

    Returns:
        One ``{code, params}`` per failed step, the tool's words as ``detail``.
    """
    return [
        {"code": result.code, "params": {"detail": result.detail}}
        for result in results
        if result.is_failed
    ]


def _load_ruleset(
    rules: RouterRulesetApplier,
    ruleset: str,
    *,
    is_diverting: bool,
    policy: RouterStepResult,
    is_cgroup_moved: bool = False,
) -> RouterStepResult:
    """Load the ruleset when it differs from what the kernel holds.

    Args:
        rules: The applier.
        ruleset: The rendered ruleset.
        is_diverting: Whether the ruleset diverts into the proxy.
        policy: The policy route step's result.
        is_cgroup_moved: Whether an engine cgroup's id differs from the one
            the loaded ruleset resolved at its load; the same text is then
            loaded again.

    Returns:
        The ruleset step's result.
    """
    is_loaded = rules.is_table_loaded()
    if is_loaded and not is_cgroup_moved and _loaded_text() == ruleset:
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
        One result per running NetBird overlay.
    """
    results = []
    for overlay in network.enabled_overlays:
        if overlay.provider != ROUTER_OVERLAY_NETBIRD:
            continue

        def converge(overlay=overlay) -> list[str]:
            note = NetbirdInboundGate().converge(is_blocked=not overlay.is_exposed)
            return [note] if note else []

        results.append(run_step(f"overlay_gate {overlay.title}", converge))
    return results
