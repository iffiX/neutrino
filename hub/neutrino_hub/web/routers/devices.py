"""The Devices tab: LAN discovery, annotations, and remote actions."""

import asyncio
import base64
import ipaddress
import json
import re
import secrets
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.cliproxyapi.ops import (
    CliproxyApiConfigApplier,
    load_config as load_cliproxyapi_config,
    save_config as save_cliproxyapi_config,
)
from neutrino_hub.modules.devices.agent_module_cache import (
    platform_keys,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.agent_module_controller import (
    ORDER_ACTION_INSTALL,
    ORDER_ACTION_UNINSTALL,
    ask_module,
)
from neutrino_hub.modules.devices.agent_sessions import (
    AgentOfflineError,
    StreamRefusedError,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_MAC_PATTERN,
    DEVICE_MODULE_COMMAND_TIMEOUT_S,
    DEVICE_REMOTE_DESKTOP_PRODUCTS,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.credentials.vault import (
    SecretVault,
    VaultError,
    VaultLockedError,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.devices.lan_scan import LanScanner
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
from neutrino_hub.modules.devices.wake_on_lan import send_magic_packet
from neutrino_hub.modules.router.link_status import RouterLinkStatus, device_addresses
from neutrino_hub import HUB_VERSION
from neutrino_hub.web.agent_tls import certificate_fingerprint
from neutrino_hub.web.constants import (
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_EVENT_DEVICES,
)
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.models import (
    DeviceAnnotation,
    DeviceClientErrorView,
    DeviceClientInfoView,
    DeviceGpuView,
    DeviceListView,
    DeviceOnlineListView,
    DeviceOnlineView,
    DeviceProcessView,
    DeviceEnrollmentRequest,
    DeviceEnrollmentView,
    DeviceInstallOrderView,
    DeviceInstallOutputView,
    DeviceModuleListView,
    DeviceModuleUpdate,
    DeviceModuleView,
    DeviceProcessKill,
    DeviceServiceAsk,
    DeviceServiceAskStarted,
    DeviceServicesView,
    DeviceSshConfig,
    DeviceView,
    DeviceActionRequest,
    RemoteDesktopPassword,
    RemoteDesktopStatusView,
    RemoteDesktopView,
    TaskStarted,
    WolResult,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/devices", tags=["devices"], dependencies=[Depends(require_session)]
)

# Actions the agent runs as one command over its socket, and what each is
# called on the wire.
AGENT_COMMAND_ACTIONS = {
    "reboot": "reboot",
    "shutdown": "shutdown",
    "reinstall_agent": "reinstall",
}

# What the drawer draws while an order stands. The machine reports the same
# words once it starts; this is what covers the moment between the click and
# the beat that carries the order down.
_ORDER_STEP_STATES = {
    ORDER_ACTION_INSTALL: "installing",
    ORDER_ACTION_UNINSTALL: "uninstalling",
}

LOGIN_KIND = "login"
ACTION_INSTALL_CLIENT = "install_client"
AUTH_KEY = "key"
AUTH_PASSWORD = "password"  # scan: allow

ENROLLMENT_TOKEN_BYTES = 18
# Long enough to walk to another machine and paste it, short enough that a
# forgotten link is not a standing invitation.
ENROLLMENT_TTL_S = 5 * 60


@router.get("", response_model=DeviceListView)
def list_devices(runtime: PanelRuntime = Depends(get_runtime)) -> DeviceListView:
    """Read the known devices cheaply, without an active sweep.

    Reads only the kernel neighbour table plus stored annotations and live agent
    metrics, so the panel can poll this every few seconds for auto-refresh
    without flooding the LAN with arp-scan broadcasts. The explicit scan is a
    separate endpoint.

    Args:
        runtime: The shared runtime.

    Returns:
        Stored devices plus whatever the neighbour table remembers.
    """
    return _device_list(runtime, is_active=False)


@router.post("/scan", response_model=DeviceListView)
def scan(runtime: PanelRuntime = Depends(get_runtime)) -> DeviceListView:
    """Actively sweep the LAN with arp-scan and return what answered.

    Args:
        runtime: The shared runtime.

    Returns:
        Every device, with the ones that answered the sweep marked online.
    """
    return _device_list(runtime, is_active=True)


@router.get("/online", response_model=DeviceOnlineListView)
def list_online(runtime: PanelRuntime = Depends(get_runtime)) -> DeviceOnlineListView:
    """The devices whose agents hold a live socket, this box's own first.

    Args:
        runtime: The shared runtime, which holds the sockets.

    Returns:
        One row per online agent.
    """
    own_addresses = {
        interface.lan.address for interface in runtime.network().lan_interfaces
    }
    registry = DeviceRegistry()
    rows = []
    for key in runtime.agent_sessions.keys():
        device = registry.get(key)
        rows.append(
            DeviceOnlineView(
                device_id=key,
                name=device.name or runtime.client_hostname.get(key, "") or key,
                hostname=runtime.client_hostname.get(key, ""),
                platform=dict(runtime.client_platform.get(key, {})),
                is_hub=runtime.client_address.get(key, "") in own_addresses,
            )
        )
    rows.sort(key=_hub_first)
    return DeviceOnlineListView(devices=rows)


def _hub_first(row: DeviceOnlineView) -> tuple:
    """Sort the hub box's own device first, then by name."""
    return (not row.is_hub, row.name.lower())


def _device_list(runtime: PanelRuntime, *, is_active: bool) -> DeviceListView:
    scanner = LanScanner(lan_interfaces=runtime.network().device_facing_device_names)
    registry = DeviceRegistry()
    return DeviceListView(
        devices=[
            _device_view(runtime, device)
            for device in registry.merged(scanner.scan(is_active=is_active))
        ]
    )


def _device_view(runtime: PanelRuntime, device: ManagedDevice) -> DeviceView:
    """One device as the panel sees it, with what its agent last reported.

    Args:
        runtime: The shared runtime, which holds the live metrics and the
            platform each agent reports.
        device: The stored device.

    Returns:
        The view, carrying the platform and the agent version on a device
        whose agent has beaten since the panel started.
    """
    key = device.mac_address.lower()
    view = _to_view(
        device,
        runtime.client_metrics.get(key),
        is_agent_online=runtime.agent_sessions.is_online(key),
        version=runtime.agent_sessions.version_of(key),
        last_seen=runtime.agent_sessions.last_seen_at(key),
        last_report_at=runtime.agent_sessions.last_report_at(key),
    )
    # Where its channel comes from wins over a scan: an agent on the overlay
    # is on no served LAN, and a machine that moved is at its new address a
    # beat later.
    view.ipv4_address = runtime.client_address.get(key) or view.ipv4_address
    platform = runtime.client_platform.get(key, {})
    if view.client is not None:
        view.client.platform_os = platform.get("os") or None
        view.client.platform_arch = platform.get("arch") or None
        view.client.hostname = runtime.client_hostname.get(key) or None
        error = runtime.client_last_error.get(key)
        if error is not None:
            view.client.last_error = DeviceClientErrorView(
                code=error.get("code", ""), params=error.get("params", {})
            )
    return view


@router.put("/{mac_address}", response_model=DeviceView)
def annotate(
    mac_address: str,
    annotation: DeviceAnnotation,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeviceView:
    """Name a device or give it SSH credentials.

    Args:
        mac_address: The device's MAC.
        annotation: The fields to change.
        runtime: The shared runtime.

    Returns:
        The device after the change, with no secret echoed back. It carries the
        metrics its agent last reported, like every other view of a device:
        built without them, the tile the page redraws from this reads as a
        machine that has gone offline until the next poll.

    Raises:
        HTTPException: 400 when the address is not a MAC, or when the SSH
            block references a credential that is not stored.
    """
    _require_mac(mac_address)
    payload = annotation.model_dump(exclude_unset=True)
    if "ssh" in payload:
        payload["ssh"] = _store_ssh_secrets(annotation.ssh)
    device = DeviceRegistry().annotate(mac_address, payload)
    runtime.events.publish(WEB_EVENT_DEVICES)
    return _device_view(runtime, device)


@router.delete("/{mac_address}")
def forget(mac_address: str, runtime: PanelRuntime = Depends(get_runtime)) -> dict:
    """Drop a device's stored annotations and everything held about it.

    The SSH key it referenced is left in the registry: keys outlive the
    devices that use them, and the Credentials page is where they are
    removed. The gateway client keys its accounts held are its alone, so
    those are revoked with it.

    What is held in memory goes with the record. A command queued for a device
    that is forgotten would otherwise be delivered to whatever machine turns up
    on that MAC next — enrol a rebuilt box and its first heartbeat drains a
    shutdown nobody asked it for.

    Args:
        mac_address: The device's MAC.
        runtime: The shared runtime, for what it holds about this device.

    Returns:
        An empty object.
    """
    _revoke_device_ai_keys(mac_address)
    DeviceRegistry().forget(mac_address)
    runtime.forget_client_state(mac_address)
    runtime.events.publish(WEB_EVENT_DEVICES)
    return {}


def _revoke_device_ai_keys(mac_address: str) -> None:
    """Remove every gateway client key a device's accounts held.

    Args:
        mac_address: The device's MAC.
    """
    is_changed = False
    with CONFIG_WRITE_LOCK:
        held = set(DeviceRegistry().get(mac_address).client.ai_key_ids.values())
        if held:
            config = load_cliproxyapi_config()
            remaining = [key for key in config.client_keys if key.id not in held]
            if len(remaining) != len(config.client_keys):
                config.client_keys = remaining
                save_cliproxyapi_config(config)
                is_changed = True
    if is_changed:
        try:
            CliproxyApiConfigApplier().apply()
        except ValueError:
            return


def _store_ssh_secrets(ssh: DeviceSshConfig | None) -> dict | None:
    """Turn a submitted SSH form into what gets stored.

    Every credential is a reference: ``key_id`` into the key registry,
    ``login_id`` into the vault's stored logins. No secret material passes
    through here.

    Args:
        ssh: The submitted credentials, or None to remove them.

    Returns:
        The dict to store, or None when credentials are being removed.

    Raises:
        HTTPException: 400 with ``{"code": "unknown_credential", "field":
            <name>}`` when a referenced id is not stored under the right kind.
    """
    if ssh is None:
        return None
    if ssh.key_id and not KeyRegistry().has_key(ssh.key_id):
        _refuse_unknown_credential("key_id")
    if ssh.login_id and not _is_stored_login(ssh.login_id):
        _refuse_unknown_credential("login_id")
    return {
        "host": ssh.host,
        "port": ssh.port,
        "username": ssh.username,
        "auth": ssh.auth,
        "key_id": ssh.key_id or None,
        "login_id": ssh.login_id or None,
    }


def _is_stored_login(login_id: str) -> bool:
    record = SecretVault().get(login_id)
    return record is not None and record.kind == LOGIN_KIND


def _refuse_unknown_credential(field: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "unknown_credential", "field": field},
    )


@router.post("/{mac_address}/wol", response_model=WolResult)
def wake(mac_address: str, runtime: PanelRuntime = Depends(get_runtime)) -> WolResult:
    """Broadcast a Wake-on-LAN packet to a device.

    Args:
        mac_address: The device's MAC.
        runtime: The shared runtime.

    Returns:
        Whether the packet was sent. Delivery says nothing about whether the
        target actually wakes: that needs Wake-on-LAN armed in its firmware and
        its NIC, which the panel cannot verify from here.
    """
    # A magic packet reaches only its own broadcast domain, and which of the
    # gateway's networks the sleeping device is on is exactly what cannot be
    # known while it is asleep. So send one to each; they are 102 bytes.
    targets = []
    for cidr in _facing_cidrs(runtime):
        try:
            subnet = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        targets.append(str(subnet.broadcast_address))
    if not targets:
        return WolResult(
            is_sent=False, message="no device-facing interface has an address"
        )

    sent = []
    for target in targets:
        try:
            send_magic_packet(mac_address, broadcast_address=target)
        except (ValueError, OSError) as error:
            return WolResult(is_sent=False, message=str(error))
        sent.append(target)
    return WolResult(
        is_sent=True,
        message=f"magic packet sent to {', '.join(sent)}",
    )


@router.post("/enrollment", response_model=DeviceEnrollmentView)
def create_enrollment(
    request: DeviceEnrollmentRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceEnrollmentView:
    """Generate a link a machine can join the gateway with.

    For machines the gateway cannot reach first — a Windows laptop, anything
    behind someone else's NAT. The owner installs the agent, opens its local
    page, and pastes this; nothing else is configured by hand.

    Args:
        request: An optional name, and an existing device to bind to.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The link, its token, and how long it lasts.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at.
    """
    link, token = _generate_enrollment_link(
        runtime, name=request.name, mac_address=request.mac_address
    )
    runtime.events.publish(WEB_EVENT_DEVICES)
    return DeviceEnrollmentView(link=link, token=token, expires_in_s=ENROLLMENT_TTL_S)


def _generate_enrollment_link(
    runtime: PanelRuntime, *, name: str, mac_address: "str | None"
) -> tuple[str, str]:
    """One ticket and the link that carries it, however the join begins.

    The panel's link button and the SSH install generate here alike, so both
    joins walk the same enrollment path. Lapsed tickets are swept on the way
    past: a ticket nobody was ever shown is a join secret lying around, and
    one that has expired is the same thing an hour later.

    Args:
        runtime: The shared runtime, which holds the open tickets.
        name: What the joining machine should be called, blank to keep what
            it has or says.
        mac_address: The device record to bind to, or None for any machine.

    Returns:
        The link and its ticket.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at; 409 with
            ``{"code": "agent_tls_missing"}`` when the channel has no
            certificate to pin.
    """
    urls = _agent_urls(runtime)
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="no served network has an address for a machine to reach",
        )
    try:
        fingerprint = certificate_fingerprint()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_tls_missing"},
        ) from error
    # One open invitation at a time: generating replaces whatever link was out,
    # so only the machine the link was just made for can join on it.
    runtime.enrollments.clear()
    token = secrets.token_urlsafe(ENROLLMENT_TOKEN_BYTES)
    runtime.enrollments[token] = {
        "name": name.strip(),
        "mac_address": (mac_address or "").lower() or None,
        "expires_at": time.time() + ENROLLMENT_TTL_S,
    }
    # The whole payload rides base64url, whose alphabet has no character a
    # shell splits or a URL escapes — the link pastes anywhere unquoted.
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"urls": urls, "token": token, "fp": fingerprint}).encode()
        )
        .decode()
        .rstrip("=")
    )
    return f"neutrino://enroll/{payload}", token


# What the drawer may ask of an agent's services: the page's own verbs and
# nothing wider. A share's access password rides inside the one ask, the way
# a mount's credentials do, and lands in a root-only file on the machine.
def _service_ask_refusal(service_type: str, body: dict) -> "str | None":
    """Why one service ask may not be queued, or None when it may.

    Args:
        service_type: The type the drawer acted on.
        body: The action's own fields, as the agent's handler takes them.

    Returns:
        A typed code, or None.
    """
    if service_type == "ai":
        return None if isinstance(body.get("targets"), dict) else "unknown_request"
    action = str(body.get("action", ""))
    if service_type == "file":
        if action == "unmount" and body.get("record_id"):
            return None
        if action == "mount" and body.get("record_id"):
            return None
        if action == "mount":
            # The hub is no account on the machine, so a fresh mount must say
            # whom it is for.
            return None if str(body.get("account", "")) else "no_target_user"
        return "unknown_request"
    if service_type == "rdp":
        return None if action in ("share", "unshare") else "unknown_request"
    return "unknown_request"


@router.get("/{mac_address}/services", response_model=DeviceServicesView)
def list_services(
    mac_address: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceServicesView:
    """Read one device's services: the catalog it is served, and its rows.

    Args:
        mac_address: The device.
        runtime: The shared runtime, for what the agent last reported.

    Returns:
        The view; empty entries mean the device has not beaten since the
        panel started.
    """
    DeviceRegistry().get(mac_address)
    key = mac_address.lower()
    entries: list = []
    host = runtime.client_device_host.get(key, "")
    if host:
        catalog, _ = runtime.device_catalog.catalog(
            device_host=host, platform=runtime.client_platform.get(key, {})
        )
        entries = list(catalog.get("services", []))
    return DeviceServicesView(
        accounts=list(runtime.client_accounts.get(key, [])), entries=entries
    )


@router.post(
    "/{mac_address}/services/{service_type}",
    response_model=DeviceServiceAskStarted,
)
def ask_service(
    mac_address: str,
    service_type: str,
    request: DeviceServiceAsk,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeviceServiceAskStarted:
    """Run one service action on a device's agent, over its socket.

    Args:
        mac_address: The device.
        service_type: The service type the drawer acted on.
        request: The action's own fields.
        runtime: The shared runtime.

    Returns:
        The ask's command id.

    Raises:
        HTTPException: 400 with the typed code for an ask outside the verb
            set, 409 when the agent is not answering.
    """
    device = DeviceRegistry().get(mac_address)
    key = device.mac_address.lower()
    if not runtime.agent_sessions.is_online(key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "agent_offline"}
        )
    body = dict(request.body)
    refused = _service_ask_refusal(service_type, body)
    if refused is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"code": refused}
        )
    command_id = f"service-{service_type}-{secrets.token_hex(4)}"
    try:
        runtime.agent_sessions.run_command_from_thread(
            key, "service", {"service_type": service_type, "body": body}
        )
    except (AgentOfflineError, StreamRefusedError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "params": dict(error.params)},
        ) from error
    return DeviceServiceAskStarted(command_id=command_id)


@router.get("/{mac_address}/modules", response_model=DeviceModuleListView)
def list_modules(
    mac_address: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceModuleListView:
    """Read every module a device could run, and where each stands.

    Args:
        mac_address: The device.
        runtime: The shared runtime, for what the agent last reported.

    Returns:
        The modules, unsupported ones included so the panel can say why.
    """
    device = DeviceRegistry().get(mac_address)
    # Lowercased, as everything else that keys by MAC is: the registry
    # normalises on the way in, and looking the runtime up by the raw path
    # segment finds nothing for a caller that used capitals.
    key = mac_address.lower()
    reported = runtime.client_modules.get(key, {})
    platform = runtime.client_platform.get(key, {})
    keys = platform_keys(platform)
    controller = runtime.agent_module_orders
    modules = []
    for name, manifest in load_module_manifests().items():
        status_ = reported.get(name, {})
        platforms = manifest.get("platforms", {})
        state = status_.get("state", "unknown")
        code = str(status_.get("code") or "")
        params = dict(status_.get("params") or {})
        # The machine answers for what is true; the controller answers for
        # how the last thing somebody asked for went. A failure the machine
        # cannot see — the hub's own fetch refusing — is only here.
        open_order = controller.open_order_for(key, name)
        failure = controller.failure_for(key, name)
        if open_order is not None:
            state = _ORDER_STEP_STATES.get(open_order.action, state)
        elif failure is not None:
            state = "failed"
            code = failure.code
            params = dict(failure.params)
        _, entry = resolve_platform_entry(manifest, platform)
        modules.append(
            DeviceModuleView(
                name=name,
                title=manifest.get("title", name),
                description=manifest.get("description", ""),
                kind=manifest.get("kind", ""),
                installer=manifest.get("installer", ""),
                # With no platform reported yet, nothing is ruled out: the
                # agent will say what it cannot do once it beats.
                is_supported=(any(key in platforms for key in keys) if keys else True),
                is_native=(entry == {}),
                source=manifest.get("source", ""),
                license=manifest.get("license", ""),
                corresponding_source=manifest.get("corresponding_source", ""),
                state=state,
                code=code,
                params=params,
            )
        )
    return DeviceModuleListView(
        modules=modules,
        is_agent_managed=device.is_managed,
        is_agent_online=runtime.agent_sessions.is_online(key),
    )


@router.put("/{mac_address}/modules/{module}", response_model=DeviceModuleListView)
def set_module(
    mac_address: str,
    module: str,
    request: DeviceModuleUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeviceModuleListView:
    """Queue one install or uninstall order for one module on a device.

    A click is one order and nothing more: the hub records no standing
    state, and what the machine reports afterwards is simply shown.

    Args:
        mac_address: The device.
        module: The module name.
        request: Which way the click went.
        runtime: The shared runtime.

    Returns:
        The modules after the order was queued.

    Raises:
        HTTPException: 404 for a module with no manifest.
    """
    manifests = load_module_manifests()
    if module not in manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown module"
        )
    key = mac_address.lower()
    if request.is_enabled is not None:
        reported = runtime.client_modules.get(key, {}).get(module) or {}
        ask_module(
            controller=runtime.agent_module_orders,
            mac_address=key,
            module=module,
            manifest=manifests[module],
            platform=runtime.client_platform.get(key, {}),
            is_enabled=request.is_enabled,
            reported_state=str(reported.get("state", "")),
        )
    return list_modules(mac_address, runtime)


@router.get("/{mac_address}/install_output", response_model=DeviceInstallOutputView)
def install_output(
    mac_address: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceInstallOutputView:
    """Every install this device has run, whatever asked for it.

    One pane, because a person reading why something is not on a machine
    should not have to know which surface started it.

    Args:
        mac_address: The device.
        runtime: The shared runtime, which holds the controller.

    Returns:
        The device's orders, newest first, each with the output its module
        produced.
    """
    manifests = load_module_manifests()
    return DeviceInstallOutputView(
        orders=[
            DeviceInstallOrderView(
                title=manifests.get(order.module, {}).get("title", order.module),
                **order.to_view(),
            )
            for order in runtime.agent_module_orders.orders(mac_address.lower())
        ]
    )


def _require_mac(mac_address: str) -> None:
    """Refuse an address that is not one.

    Every device is keyed by its MAC — the registry, the host-key store, the
    command queue and the magic packet all address it that way — so a name
    that is not a MAC is a record none of them can act on and one the panel
    cannot delete by any other route.

    Args:
        mac_address: What was in the path.

    Raises:
        HTTPException: 400 when it is not a MAC.
    """
    if not re.match(DEVICE_MAC_PATTERN, mac_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{mac_address!r} is not a MAC address",
        )


def _agent_urls(runtime: PanelRuntime) -> list:
    """Every address a machine could be told to reach the agent channel on.

    All of them, not one: a hub serves more than one network, only one of its
    addresses is on the network of the machine being enrolled, and neither the
    hub nor the person pasting the link knows which. The agent tries them in
    turn.

    Args:
        runtime: The shared runtime, for the device-facing networks and the
            port.

    Returns:
        Base ``https`` URLs, in configuration order.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    urls = []
    for cidr in _facing_cidrs(runtime):
        urls.append(f"https://{cidr.split('/')[0]}:{port}")
    return urls


def _facing_cidrs(runtime: PanelRuntime) -> list:
    """IPv4 CIDRs of the networks devices reach this hub on.

    A served network's address is configuration; an exposed port on a
    ``server`` has whatever address the machine's own manager gave it, which
    only the live link can answer. An exposed overlay is neither: nobody
    plugged it in, and a machine that is only on the overlay has no other way
    to be told where the hub is.

    Args:
        runtime: The shared runtime, for the network configuration.

    Returns:
        CIDR strings in configuration order, the overlays last.
    """
    network = runtime.network()
    reader = None
    cidrs = []
    for interface in network.device_facing_interfaces:
        if interface.is_lan and interface.lan.address:
            cidrs.append(interface.lan.cidr)
            continue
        if reader is None:
            reader = RouterLinkStatus()
        live = reader.link(interface.device_name).ipv4_address
        if live:
            cidrs.append(live)
    addresses = device_addresses()
    for name in network.exposed_overlay_device_names:
        live = addresses.get(name, "")
        if live and live not in cidrs:
            cidrs.append(live)
    return cidrs


@router.post("/{mac_address}/kill_process")
def kill_process(
    mac_address: str,
    request: DeviceProcessKill,
    runtime: PanelRuntime = Depends(get_runtime),
) -> dict:
    """End one process on a device, through its agent.

    Args:
        mac_address: The device's MAC.
        request: The process id to signal.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 400 for a pid no one should signal, 404 when no such
            process runs, 409 when the agent is not answering, 502 when the
            device refused the signal.
    """
    if request.pid <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "kill_failed", "params": {"pid": request.pid}},
        )
    key = DeviceRegistry().get(mac_address).mac_address.lower()
    info = _run_device_command(runtime, key, "kill_process", {"pid": request.pid})
    code = str(info.get("code", "") or "")
    if code == "process_missing":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": code, "params": dict(info.get("params") or {})},
        )
    if code or int(info.get("exit_code", 1) or 0) != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": code or "kill_failed",
                "params": dict(info.get("params") or {}),
            },
        )
    return {}


def _run_device_command(runtime: PanelRuntime, key: str, action: str, args: dict):
    """Run one command on a device's agent and wait for its close.

    Args:
        runtime: The shared runtime.
        key: The device.
        action: The command's action.
        args: The action's arguments.

    Returns:
        What the agent closed with.

    Raises:
        HTTPException: 409 with the code when the device has no channel or
            the agent refused the stream.
    """
    try:
        return runtime.agent_sessions.run_command_from_thread(
            key, action, args, timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S
        )
    except (AgentOfflineError, StreamRefusedError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "params": dict(error.params)},
        ) from error


@router.post("/{mac_address}/action", response_model=TaskStarted)
async def start_action(
    mac_address: str,
    request: DeviceActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Start a long-running action on a device.

    ``install_client`` puts the agent on a machine over SSH, with the
    credentials the request carries; ``reinstall_agent``, ``reboot`` and
    ``shutdown`` are commands on the device's agent. Remote desktop has its
    own endpoints.

    Declared async deliberately: it schedules the background job on the running
    event loop, which a threadpool route would not have.

    Args:
        mac_address: The device's MAC.
        request: Which action to run, and for an install how to reach the
            machine.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from.

    Raises:
        HTTPException: 400 for an unknown action or an install naming no
            single credential, 409 with ``agent_offline`` when the device
            has no live agent for a command, or 409 when the install's
            pre-flight finds a device that is not Linux
            (``{"code": "unsupported_remote_install", "os": ...}``).
    """
    registry = DeviceRegistry()
    device = registry.get(mac_address)
    action = request.action

    if action in AGENT_COMMAND_ACTIONS:
        key = device.mac_address.lower()
        if not runtime.agent_sessions.is_online(key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail={"code": "agent_offline"}
            )
        stream = runtime.tasks.start(
            label=f"{action} {mac_address}",
            source=_agent_command_stream(runtime, key, AGENT_COMMAND_ACTIONS[action]),
        )
        runtime.events.publish(WEB_EVENT_DEVICES)
        return TaskStarted(task_id=stream.id)

    if action != ACTION_INSTALL_CLIENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_action", "params": {"action": action}},
        )
    credentials = await asyncio.to_thread(_install_credentials, device, request)
    operator = DeviceSshOperator(credentials=credentials)
    # Pre-flight, refused before a task starts. A probe that failed — device
    # off, wrong credentials — is not a refusal: the task runs and its log
    # reports the failure, the same surface as every mid-install one.
    code, kernel = await operator.run_once("uname -s")
    if code == 0 and kernel and kernel != "Linux":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "unsupported_remote_install", "os": kernel},
        )
    packages = runtime.agent_packages
    if not packages.has_packages():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_package_missing"},
        )
    # A ticket, not a heartbeat token: the install walks the same enrollment
    # path a pasted link does, and a failed install leaves any live agent
    # beating exactly as it was.
    link, _ = _generate_enrollment_link(
        runtime, name=device.name or "", mac_address=mac_address
    )
    # Under the device's own install lock, which the module controller takes
    # too: putting the agent on a machine and installing a module on it are
    # two package managers on one machine, and only one may run.
    stream = runtime.tasks.start(
        label=f"install_client {mac_address.lower()}",
        source=_locked_install(
            runtime,
            mac_address,
            operator.install_client(
                packages=packages,
                enrollment_link=link,
                sudo_password=request.sudo_password or None,
            ),
        ),
    )
    runtime.events.publish(WEB_EVENT_DEVICES)
    return TaskStarted(task_id=stream.id)


def _install_credentials(
    device: ManagedDevice, request: DeviceActionRequest
) -> SshCredentials:
    """Store the install's SSH block and open the credentials it names.

    Exactly one credential source is taken: a stored key, a stored login,
    or a password typed now. A typed password is stored as a vault login
    only when asked, and the device's block records the id. The sudo
    password is not looked at here and is written nowhere.

    Args:
        device: The device being installed on.
        request: The install request.

    Returns:
        The credentials the install connects with.

    Raises:
        HTTPException: 400 when the request names no host or username, or
            not exactly one credential source, or a stale id.
    """
    sources = [
        name for name in ("key_id", "login_id", "password") if getattr(request, name)
    ]
    if len(sources) != 1 or not request.host.strip() or not request.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "install_credentials_invalid", "params": {}},
        )
    host = request.host.strip()
    username = request.username.strip()
    login_id = request.login_id
    with CONFIG_WRITE_LOCK:
        if request.password and request.is_password_saved:
            try:
                login_id = (
                    SecretVault()
                    .add(
                        kind=LOGIN_KIND,
                        name=f"{username}@{host}",
                        secret={"username": username, "password": request.password},
                    )
                    .id
                )
            except VaultLockedError:
                raise
            except VaultError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "login_rejected", "params": {}},
                ) from error
        stored = _store_ssh_secrets(
            DeviceSshConfig(
                host=host,
                port=request.port,
                username=username,
                auth=AUTH_KEY if request.key_id else AUTH_PASSWORD,
                key_id=request.key_id,
                login_id=login_id,
            )
        )
        DeviceRegistry().annotate(device.mac_address, {"ssh": stored})
    credentials = SshCredentials.from_dict(stored)
    if request.password:
        credentials.password = request.password
    return credentials


async def _locked_install(
    runtime: PanelRuntime, mac_address: str, source: AsyncIterator[str]
) -> AsyncIterator[str]:
    """Run an install stream while holding the device's install lock.

    Args:
        runtime: The shared runtime, which owns the locks.
        mac_address: The device.
        source: The install's own output.

    Yields:
        A line saying it is waiting when something else holds the lock, then
        everything the install produces.
    """
    if runtime.device_install_locks.is_held(mac_address):
        yield "[waiting for the install already running on this device]\n"
    async with runtime.device_install_locks.hold_async(mac_address):
        async for chunk in source:
            yield chunk


@router.get("/{mac_address}/remote_desktop", response_model=RemoteDesktopView)
def remote_desktop_status(
    mac_address: str, runtime: PanelRuntime = Depends(get_runtime)
) -> RemoteDesktopView:
    """Report what remote-desktop software is on a device.

    AnyDesk and TeamViewer are read by the agent on request; RustDesk is a
    module this hub installs, and its id rides the report with that
    module's block, so a device whose agent is quiet still shows it.

    Args:
        mac_address: The device's MAC.
        runtime: The shared runtime.

    Returns:
        Each agent-read product's state, and RustDesk's id when the machine
        has reported one.
    """
    device = DeviceRegistry().get(mac_address)
    key = device.mac_address.lower()
    cards = {}
    for product in DEVICE_REMOTE_DESKTOP_PRODUCTS:
        try:
            info = runtime.agent_sessions.run_command_from_thread(
                key,
                "remote_desktop_status",
                {"product": product},
                timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S,
            )
        except (AgentOfflineError, StreamRefusedError) as error:
            cards[product] = _remote_desktop_unreachable(product, error.code)
            continue
        cards[product] = _remote_desktop_view(product, info)
    return RemoteDesktopView(
        anydesk=cards["anydesk"],
        teamviewer=cards["teamviewer"],
        rustdesk_id=_reported_rustdesk_id(runtime, key),
    )


def _remote_desktop_unreachable(product: str, code: str) -> RemoteDesktopStatusView:
    """One product's card on a device that could not be asked.

    Args:
        product: The product the card is for.
        code: Why the device could not be asked.

    Returns:
        A card that says why it is empty rather than one reading "not
        installed" about a machine nobody asked.
    """
    return RemoteDesktopStatusView(
        product=product,
        is_installed=False,
        is_running=False,
        unreachable=code,
        session_id=None,
        can_set_password=False,
    )


def _remote_desktop_view(product: str, info: dict) -> RemoteDesktopStatusView:
    """One product's card from what the agent closed its status with."""
    code = str(info.get("code", "") or "")
    if code:
        return _remote_desktop_unreachable(product, code)
    result = info.get("result") if isinstance(info.get("result"), dict) else {}
    session_id = result.get("session_id")
    return RemoteDesktopStatusView(
        product=product,
        is_installed=bool(result.get("is_installed")),
        is_running=bool(result.get("is_running")),
        session_id=str(session_id) if session_id else None,
        can_set_password=bool(result.get("can_set_password", True)),
    )


def _reported_rustdesk_id(runtime: PanelRuntime, mac_address: str) -> str:
    """The RustDesk id one machine's module report carries.

    Args:
        runtime: The shared runtime.
        mac_address: The device's MAC.

    Returns:
        The id, empty when the machine has not reported one.
    """
    status_ = (runtime.client_modules.get(mac_address) or {}).get("rustdesk")
    if not isinstance(status_, dict):
        return ""
    details = status_.get("details")
    if not isinstance(details, dict):
        return ""
    return str(details.get("rustdesk_id", "") or "")


@router.post(
    "/{mac_address}/remote_desktop/{product}/password", response_model=TaskStarted
)
async def set_remote_desktop_password(
    mac_address: str,
    product: str,
    request: RemoteDesktopPassword,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Set a product's unattended-access password on a device.

    Args:
        mac_address: The device's MAC.
        product: One of ``DEVICE_REMOTE_DESKTOP_PRODUCTS``.
        request: The password to set.
        runtime: The shared runtime.

    Returns:
        A task id to stream the result from.

    Raises:
        HTTPException: 400 for an unknown product, 409 when the agent is
            not answering.
    """
    if product not in DEVICE_REMOTE_DESKTOP_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "product_unknown", "params": {"product": product}},
        )
    key = DeviceRegistry().get(mac_address).mac_address.lower()
    if not runtime.agent_sessions.is_online(key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "agent_offline"}
        )
    stream = runtime.tasks.start(
        label=f"set {product} password {mac_address}",
        source=_agent_command_stream(
            runtime,
            key,
            "remote_desktop_password",
            {"product": product, "password": request.password},
        ),
    )
    return TaskStarted(task_id=stream.id)


async def _agent_command_stream(
    runtime: PanelRuntime, key: str, action: str, args: "dict | None" = None
) -> AsyncIterator[str]:
    """Run one command on a device's agent, streaming what it prints.

    Args:
        runtime: The shared runtime, which holds the sockets.
        key: The device.
        action: The command's action on the wire.
        args: The action's arguments.

    Yields:
        Each line the agent sends, then the close's output and its code.
    """
    try:
        stream = await runtime.agent_sessions.open_stream(
            key, "command", {"action": action, "args": dict(args or {})}
        )
    except (AgentOfflineError, StreamRefusedError) as error:
        yield json.dumps({"code": error.code, "params": dict(error.params)}) + "\n"
        return
    while True:
        item = await stream.recv()
        if item is None:
            break
        if item[0] == "event":
            yield str(item[1].get("line", "")) + "\n"
    info = stream.close_info or {}
    output = str(info.get("output", "") or "")
    if output:
        yield output if output.endswith("\n") else output + "\n"
    if info.get("code"):
        yield json.dumps({"code": info["code"], "params": info.get("params") or {}})
        yield "\n"
    elif "exit_code" in info:
        yield f"[exit {info['exit_code']}]\n"


def _to_view(
    device: ManagedDevice,
    metrics: dict | None = None,
    *,
    is_agent_online: bool = False,
    version: str = "",
    last_seen: "str | None" = None,
    last_report_at: "str | None" = None,
) -> DeviceView:
    ssh_view = None
    if device.ssh:
        # The block holds only references, so the ids can be echoed for the
        # drawer's pickers. The key is named so the drawer can show which one
        # is selected without exposing anything.
        key_id = device.ssh.get("key_id")
        key_name = None
        if key_id:
            record = KeyRegistry().get(key_id)
            key_name = record.name if record else "(deleted key)"
        ssh_view = DeviceSshConfig(
            host=device.ssh.get("host", ""),
            port=device.ssh.get("port", 22),
            username=device.ssh.get("username", ""),
            auth=device.ssh.get("auth", AUTH_KEY),
            key_id=key_id,
            key_name=key_name,
            login_id=device.ssh.get("login_id"),
        )
    client_view = None
    if device.is_managed:
        latest = metrics or {}
        client_view = DeviceClientInfoView(
            is_managed=True,
            is_online=is_agent_online,
            version=version or None,
            is_version_mismatched=_is_version_mismatched(version),
            last_seen=last_seen,
            last_report_at=last_report_at,
            cpu_percent=latest.get("cpu_percent"),
            memory_percent=latest.get("memory_percent"),
            disk_percent=latest.get("disk_percent"),
            temperature_c=latest.get("temperature_c"),
            uptime_s=latest.get("uptime_s"),
            load_average=latest.get("load_average") or [],
            cpu_core_percents=latest.get("cpu_core_percents") or [],
            gpus=[DeviceGpuView(**gpu) for gpu in latest.get("gpus") or []],
            processes=[
                DeviceProcessView(**process)
                for process in latest.get("processes") or []
            ],
        )
    return DeviceView(
        mac_address=device.mac_address,
        ipv4_address=device.ipv4_address,
        name=device.name,
        icon=device.icon,
        vendor=device.vendor,
        # A beating agent is proof of reachability the ARP sweep cannot give:
        # a machine on the overlay has no neighbour entry on any LAN.
        is_online=device.is_online or is_agent_online,
        is_agent_online=is_agent_online,
        is_wol_enabled=device.is_wol_enabled,
        has_ssh=device.has_ssh,
        is_stored=device.is_stored,
        ssh=ssh_view,
        client=client_view,
    )


def _is_version_mismatched(agent_version: "str | None") -> bool:
    """Whether an agent is a different version from this hub.

    The two are released together and supported only together
    (docs/standard/agent_work_rule/release.md), so any difference means the
    device needs its agent upgraded. A device that has never reported one is
    not a mismatch, only unknown.

    Args:
        agent_version: What the agent last reported, if anything.

    Returns:
        True when the versions differ.
    """
    if not agent_version:
        return False
    return agent_version.split("+")[0] != HUB_VERSION.split("+")[0]
