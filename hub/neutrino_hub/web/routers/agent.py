"""Endpoints the neutrino_agent agents talk to.

These are the only routes without a session: agents authenticate with a
per-device token issued when the agent was installed. They are served on the
agent channel's own TLS port, never on the panel's, and every enrollment link
carries the certificate fingerprint the agent pins.

A heartbeat now carries more than metrics: the agent reports which features it
is reconciling and in what state, and the reply tells it which features should
be on and — when its catalog is stale — how to obtain each one. The gateway
resolves the parts an agent cannot know for itself, chiefly the AI endpoint
and the client key minted for that device.
"""

import ipaddress
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config,
    save_config,
)
from neutrino_hub.modules.credentials.registry import AiProviderRegistry
from neutrino_hub.modules.devices.constants import DEVICE_MAC_PATTERN
from neutrino_hub.modules.devices.registry import (
    DeviceRegistry,
    ManagedDevice,
    feature_wish,
)
from neutrino_hub.modules.features.catalog import catalog_hash, load_catalog
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    ClientCommand,
    ClientCommandResult,
    ClientEnroll,
    ClientEnrollReply,
    ClientHeartbeat,
    ClientHeartbeatReply,
    ClientLeave,
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
        The desired features, the catalog when the agent's is stale, and any
        queued commands.

    Raises:
        HTTPException: 401 when the token matches no device.
    """
    registry = DeviceRegistry()
    device = registry.find_by_client_token(beat.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown client token"
        )
    if beat.feature_requests:
        # A request from the machine's own page carries whichever wish was
        # changed there; the rest is left as the panel has it.
        for feature, wish in beat.feature_requests.items():
            if isinstance(wish, dict):
                device = registry.set_feature(
                    device.mac_address,
                    feature,
                    is_enabled=wish.get("is_enabled"),
                    is_activated=wish.get("is_activated"),
                )
            else:
                device = registry.set_feature(
                    device.mac_address, feature, is_enabled=bool(wish)
                )
    runtime.client_metrics[device.mac_address] = dict(beat.metrics)
    runtime.client_features[device.mac_address] = dict(beat.features)
    if beat.platform:
        runtime.client_platform[device.mac_address] = dict(beat.platform)
    registry.record_heartbeat(
        device.mac_address,
        version=beat.client_version,
        seen_at=datetime.now(timezone.utc).isoformat(),
    )

    catalog = load_catalog()
    served_hash = catalog_hash(catalog)
    desired = _desired_features(device, runtime, registry)
    return ClientHeartbeatReply(
        commands=[
            ClientCommand(**command)
            for command in runtime.take_client_commands(device.mac_address)
        ],
        desired_features=desired,
        catalog=catalog if beat.catalog_hash != served_hash else None,
        catalog_hash=served_hash,
    )


@router.post("/enroll", response_model=ClientEnrollReply)
def enroll(
    request: ClientEnroll, runtime: PanelRuntime = Depends(get_runtime)
) -> ClientEnrollReply:
    """Let a machine introduce itself with an enrollment ticket.

    This is how a machine the gateway cannot reach — no SSH, or behind
    someone else's NAT — joins: its owner pastes a link into the agent's own
    page and the machine comes to the gateway rather than the other way
    round. A ticket minted for an already-known device binds to it; one
    minted blank creates a device keyed by the machine's own id.

    Args:
        request: The ticket and what the machine says it is.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The heartbeat token and the key the device is stored under.

    Raises:
        HTTPException: 401 when the ticket is unknown or has expired.
    """
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
    return ClientEnrollReply(token=token, mac_address=key)


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
    runtime.client_metrics.pop(device.mac_address, None)
    runtime.client_features.pop(device.mac_address, None)
    runtime.client_platform.pop(device.mac_address, None)
    return {}


@router.post("/result")
def result(report: ClientCommandResult) -> dict:
    """Accept an agent's report of how a command went.

    Args:
        report: The command outcome.

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
    return {}


def _desired_features(
    device: ManagedDevice, runtime: PanelRuntime, registry: DeviceRegistry
) -> dict:
    """What each of a device's features should be, with configs resolved.

    Args:
        device: The device the heartbeat came from.
        runtime: The shared runtime, for the gateway's addresses.
        registry: The device registry, for minting a device's AI key.

    Returns:
        Feature name to ``{"is_enabled", "config"}``.
    """
    desired = {}
    for feature, stored in device.client.features.items():
        wanted = feature_wish(stored)
        config = {}
        if feature == "ai_tools" and wanted["is_enabled"]:
            config = _ai_config(device, runtime, registry)
        desired[feature] = {**wanted, "config": config}
    return desired


def _ai_config(
    device: ManagedDevice, runtime: PanelRuntime, registry: DeviceRegistry
) -> dict:
    """Resolve where a device's AI tools should point, minting a key if needed.

    Args:
        device: The device.
        runtime: The shared runtime.
        registry: The device registry.

    Returns:
        ``{"base_url", "api_key", "target_user", "tools"}``.
    """
    config = load_config()
    key = _device_key(device, config, registry)
    port = config.listen_port
    base_url = f"{_gateway_host(runtime, device.ipv4_address)}:{port}"
    return {
        "base_url": base_url,
        "api_key": key.key if key else "",
        "target_user": device.client.target_user
        or (device.ssh or {}).get("username", ""),
        "tools": ["claude", "codex", "gemini"],
        "model": _served_model(),
    }


def _served_model() -> str:
    """The model name a device's tools should ask the hub for.

    A tool asks for a model by name, and the names the hub serves are the
    ones its providers publish — a device asking for ``claude-sonnet-4-5``
    against a DeepSeek provider gets nothing. The first model of the first
    enabled provider is what a device is told to ask for; a provider that
    publishes its models under Claude's own names needs none of this and is
    left to answer for them.

    Returns:
        A model name, or empty when no provider names one.
    """
    for provider in AiProviderRegistry().list_records():
        if not provider.is_enabled or not provider.secret_id:
            continue
        for entry in provider.models:
            served = str(entry.get("alias") or entry.get("name") or "").strip()
            if served:
                return served
    return ""


def _device_key(device: ManagedDevice, config, registry: DeviceRegistry):
    """The device's cliproxyapi client key, minting and applying one on first need.

    Args:
        device: The device.
        config: The loaded cliproxyapi configuration.
        registry: The device registry.

    Returns:
        The client key, or None when the gateway has none to give.
    """
    key_id = device.client.ai_key_id
    existing = next((k for k in config.client_keys if k.id == key_id), None)
    if existing is not None:
        return existing
    key = CliproxyApiClientKey.minted(device.name or device.mac_address)
    config.client_keys.append(key)
    save_config(config)
    registry.set_ai_key_id(device.mac_address, key.id)
    try:
        CliproxyApiConfigApplier().apply()
    except ValueError:
        pass
    return key


def _gateway_host(runtime: PanelRuntime, device_ip: str) -> str:
    """The ``http://<address>`` a device should reach the gateway on.

    Args:
        runtime: The shared runtime.
        device_ip: The device's address, to pick the LAN it is on.

    Returns:
        The scheme and host, without a port.
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
    return f"http://{address or fallback or '192.168.100.1'}"
