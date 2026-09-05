"""Endpoints the neutrino_agent agents talk to.

These are the only routes without a session: agents authenticate with a
per-device token issued when the agent was installed. They are served on the
agent channel's own TLS port, never on the panel's, and every enrollment link
carries the certificate fingerprint the agent pins.

A heartbeat carries the machine's report — metrics, accounts, per-module
state — and the reply carries what should be true: the desired modules,
the catalog when the agent's copy is stale, and a gateway credential for
each account whose AI target is on. The credential is the one per-device
secret the reply resolves; the catalog itself carries none.
"""

import hashlib
import ipaddress
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config,
    save_config,
)
from neutrino_hub.modules.credentials.vault import VaultLockedError
from neutrino_hub.modules.devices.agent_package import agent_packages
from neutrino_hub.modules.devices.constants import DEVICE_MAC_PATTERN
from neutrino_hub.modules.devices.registry import (
    DeviceRegistry,
    ManagedDevice,
    module_wish,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.utils.version_number import parse_version
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    ClientCommand,
    ClientCommandResult,
    ClientEnroll,
    ClientEnrollReply,
    ClientHeartbeat,
    ClientHeartbeatReply,
    ClientLeave,
    ClientPackageRequest,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/heartbeat", response_model=ClientHeartbeatReply)
def heartbeat(
    beat: ClientHeartbeat, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientHeartbeatReply:
    """Record an agent's report and hand back what should be true.

    Args:
        beat: The heartbeat payload.
        runtime: The shared runtime.

    Returns:
        The desired modules, the catalog when the agent's is stale, the
        per-account AI credentials, and any queued commands.

    Raises:
        HTTPException: 401 when the token matches no device, 409 when the
            agent is a later release than this hub.
    """
    registry = DeviceRegistry()
    device = registry.find_by_client_token(beat.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown client token"
        )
    _refuse_newer_agent(beat.client_version)
    if beat.module_requests:
        # A request from the machine's own page carries whichever wish was
        # changed there; the rest is left as the panel has it.
        for module, wish in beat.module_requests.items():
            if isinstance(wish, dict):
                device = registry.set_module(
                    device.mac_address,
                    module,
                    is_enabled=wish.get("is_enabled"),
                    is_activated=wish.get("is_activated"),
                )
            else:
                device = registry.set_module(
                    device.mac_address, module, is_enabled=bool(wish)
                )
    key = device.mac_address
    runtime.client_metrics[key] = dict(beat.metrics)
    runtime.client_modules[key] = dict(beat.modules)
    runtime.client_accounts[key] = list(beat.accounts)
    if beat.platform:
        runtime.client_platform[key] = dict(beat.platform)
    if beat.hostname:
        runtime.client_hostname[key] = beat.hostname
    if isinstance(beat.last_error, dict) and beat.last_error.get("code"):
        runtime.client_last_error[key] = {
            "code": str(beat.last_error.get("code")),
            "params": dict(beat.last_error.get("params") or {}),
        }
    else:
        runtime.client_last_error.pop(key, None)
    registry.record_heartbeat(
        device.mac_address,
        version=beat.client_version,
        seen_at=datetime.now(timezone.utc).isoformat(),
    )

    device_host = _device_host(runtime, device.ipv4_address)
    ai_accounts = _ai_accounts(device, runtime, registry, beat.ai_targets, device_host)
    catalog, served_hash = runtime.device_catalog.catalog(device_host=device_host)
    return ClientHeartbeatReply(
        commands=[
            ClientCommand(**command)
            for command in runtime.take_client_commands(device.mac_address)
        ],
        desired_modules=_desired_modules(device),
        catalog=catalog if beat.catalog_hash != served_hash else None,
        catalog_hash=served_hash,
        ai_accounts=ai_accounts,
        hub_version=HUB_VERSION,
    )


@router.post("/enroll", response_model=ClientEnrollReply)
def enroll(
    request: ClientEnroll, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientEnrollReply:
    """Let a machine introduce itself with an enrollment ticket.

    This is how a machine the gateway cannot reach — no SSH, or behind
    someone else's NAT — joins: its owner pastes a link into the agent's own
    page and the machine comes to the gateway rather than the other way
    round. A ticket generated for an already-known device binds to it; one
    generated blank creates a device keyed by the machine's own id.

    Args:
        request: The ticket and what the machine says it is.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The heartbeat token and the key the device is stored under.

    Raises:
        HTTPException: 401 when the ticket is unknown or has expired, 409
            when the agent is a later release than this hub — judged before
            the ticket so a refused machine has not spent the link.
    """
    _refuse_newer_agent(request.client_version)
    # Taken before it is judged: a ticket leaves the store in one step, so
    # two machines racing the same link cannot both spend it.
    ticket = runtime.enrollments.pop(request.enrollment_token, None)
    if ticket is None or ticket["expires_at"] < time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="that enrollment link is unknown or has expired",
        )

    registry = DeviceRegistry()
    key = ticket.get("mac_address") or _reported_key(registry, request)
    device = registry.get(key)
    name = ticket.get("name") or device.name or request.hostname or key
    registry.annotate(key, {"name": name})
    token = registry.issue_client_token(key)
    if request.platform:
        runtime.client_platform[key] = dict(request.platform)
    if request.hostname:
        runtime.client_hostname[key] = request.hostname
    return ClientEnrollReply(token=token, mac_address=key, hub_version=HUB_VERSION)


def _reported_key(registry: DeviceRegistry, request: ClientEnroll) -> str:
    """The record an unbound enrollment lands on.

    A machine that reports its MACs joins as the device a scan or an SSH
    setup already listed rather than as a second record, an already-stored
    MAC winning over the rest. A machine reporting nothing usable — overlay
    only, or another platform — is keyed by its machine id.

    Args:
        registry: The stored devices.
        request: What the machine said it is.

    Returns:
        The key the device is stored under.
    """
    reported = [
        address.lower()
        for address in request.mac_addresses
        if re.fullmatch(DEVICE_MAC_PATTERN, address or "")
    ]
    for address in reported:
        if registry.get(address).is_stored:
            return address
    if reported:
        return reported[0]
    return f"id:{request.device_id[:24]}"


@router.post("/leave")
def leave(report: ClientLeave, runtime: PanelRuntime = Depends(get_runtime)) -> dict:
    """Accept an agent's word that it is leaving.

    Called when someone disconnects a machine from its own agent page. The
    device stays in the list with everything the user gave it; only the agent
    and what it reported are dropped, so the panel stops drawing metrics that
    have stopped arriving.

    Args:
        report: Carries the leaving agent's token.
        runtime: The shared runtime, which holds the live reports.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 401 when the token matches no device.
    """
    registry = DeviceRegistry()
    device = registry.find_by_client_token(report.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown client token"
        )
    registry.forget_client(device.mac_address)
    runtime.forget_client_state(device.mac_address)
    return {}


@router.post("/result")
def result(
    report: ClientCommandResult, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Accept an agent's report of how a command went.

    The last outcome per command id is kept in the runtime, so the device
    drawer can show how a reboot went after its stream has closed.

    Args:
        report: The command outcome.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 401 when the token matches no device.
    """
    device = DeviceRegistry().find_by_client_token(report.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown client token"
        )
    outcomes = runtime.client_command_results.setdefault(device.mac_address, {})
    outcomes[report.id] = {
        "id": report.id,
        "exit_code": report.exit_code,
        "output": report.output,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    return {}


@router.post("/package")
def package(request: ClientPackageRequest) -> Response:
    """Hand an agent the hub's baked package for its family.

    This is how an older agent updates itself: the reply's ``hub_version``
    tells it to move, and this hands it the same build an SSH install would
    deliver, over the same pinned channel its heartbeats use.

    Args:
        request: The token and the package family.

    Returns:
        The package bytes, with their SHA-256 in ``X-Checksum-Sha256``.

    Raises:
        HTTPException: 401 when the token matches no device, 409 when the
            hub holds no package for the family.
    """
    device = DeviceRegistry().find_by_client_token(request.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown client token"
        )
    path = agent_packages().get(request.family)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_package_missing"},
        )
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-Checksum-Sha256": hashlib.sha256(data).hexdigest()},
    )


def _refuse_newer_agent(agent_version: str) -> None:
    """Turn away an agent from a later release than this hub.

    The two ship together and are supported only together, so a newer agent
    is not negotiated with — the hub must be updated first. A version that
    does not parse on either side refuses nothing.

    Args:
        agent_version: What the agent reported itself as.

    Raises:
        HTTPException: 409 naming both versions.
    """
    agent = parse_version(agent_version)
    hub = parse_version(HUB_VERSION)
    if agent is None or hub is None or agent <= hub:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "agent_newer_than_hub",
            "params": {"hub_version": HUB_VERSION, "agent_version": agent_version},
        },
    )


def _desired_modules(device: ManagedDevice) -> dict:
    """What each of a device's modules should be.

    Args:
        device: The device the heartbeat came from.

    Returns:
        Module name to ``{"is_enabled", "is_activated"}``.
    """
    return {
        module: module_wish(stored) for module, stored in device.client.modules.items()
    }


def _ai_accounts(
    device: ManagedDevice,
    runtime: PanelRuntime,
    registry: DeviceRegistry,
    targets: dict,
    device_host: str,
) -> dict:
    """Resolve the gateway credential for each account whose target is on.

    A locked vault fails only this part of the beat: the reply simply omits
    ``ai_accounts`` for the turn.

    Args:
        device: The device the heartbeat came from.
        runtime: The shared runtime.
        registry: The device registry.
        targets: The beat's ``ai_targets``.
        device_host: The address the device reaches the hub on.

    Returns:
        ``{account: {"base_url", "api_key", "model"}}``.
    """
    try:
        keys = _account_keys(device, registry, targets)
        materials = {account: key.open_key() for account, key in keys.items()}
    except VaultLockedError:
        return {}
    if not materials:
        return {}
    port = load_config().listen_port
    base_url = f"http://{device_host}:{port}"
    model = runtime.served_models.first_model(
        port=port, client_key=next(iter(materials.values()))
    )
    return {
        account: {"base_url": base_url, "api_key": material, "model": model}
        for account, material in materials.items()
    }


def _account_keys(
    device: ManagedDevice, registry: DeviceRegistry, targets: dict
) -> dict:
    """The client key of each account turned on, revoking the ones turned off.

    An account turned on whose stored id names no key on the gateway — it
    was revoked, or the record was dropped — is issued a fresh one.

    Args:
        device: The device the heartbeat came from.
        registry: The device registry.
        targets: The beat's ``ai_targets``.

    Returns:
        Account name to its stored key.

    Raises:
        VaultLockedError: If there is no data key to seal a new key under.
    """
    if not targets:
        return {}
    keys = {}
    is_changed = False
    with CONFIG_WRITE_LOCK:
        stored = DeviceRegistry().get(device.mac_address)
        config = load_config()
        by_id = {key.id: key for key in config.client_keys}
        for account in sorted(targets):
            key_id = stored.client.ai_key_ids.get(account)
            if targets[account]:
                key = by_id.get(key_id)
                if key is None:
                    key = CliproxyApiClientKey.generated(
                        f"{device.name or device.mac_address}/{account}"
                    )
                    config.client_keys.append(key)
                    registry.set_ai_key_id(device.mac_address, account, key.id)
                    is_changed = True
                keys[account] = key
                continue
            if key_id is None:
                continue
            if key_id in by_id:
                config.client_keys = [k for k in config.client_keys if k.id != key_id]
                is_changed = True
            registry.set_ai_key_id(device.mac_address, account, None)
        if is_changed:
            save_config(config)
    if is_changed:
        try:
            CliproxyApiConfigApplier().apply()
        except ValueError:
            pass
    return keys


def _device_host(runtime: PanelRuntime, device_ip: str) -> str:
    """The address a device reaches the hub on.

    Every hub-self host in the catalog and the AI credential resolves to
    this, so what the device stores is an address it can actually open.

    Args:
        runtime: The shared runtime.
        device_ip: The device's address, to pick the LAN it is on.

    Returns:
        The bare address, without a scheme or port.
    """
    address = None
    fallback = None
    for interface in runtime.network().lan_interfaces:
        lan = interface.lan
        fallback = fallback or lan.address
        try:
            network = ipaddress.ip_network(lan.cidr, strict=False)
            if device_ip and ipaddress.ip_address(device_ip) in network:
                address = lan.address
                break
        except ValueError:
            continue
    return address or fallback or "192.168.100.1"
