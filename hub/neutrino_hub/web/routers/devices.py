"""The Devices tab: LAN discovery, annotations, and remote actions."""

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
    ORDER_ACTION_DISABLE,
    ORDER_ACTION_ENABLE,
    ORDER_ACTION_INSTALL,
    ORDER_ACTION_REMOVE,
    ask_module,
)
from neutrino_hub.modules.devices.agent_package import agent_packages
from neutrino_hub.modules.devices.constants import DEVICE_MAC_PATTERN
from neutrino_hub.modules.devices.registry import (
    DeviceRegistry,
    ManagedDevice,
    module_wish,
)
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.devices.lan_scan import LanScanner
from neutrino_hub.modules.devices.remote_desktop import (
    SUPPORTED_PRODUCTS,
)
from neutrino_hub.modules.devices.remote_desktop import (
    RemoteDesktopManager,
    RemoteDesktopStatus,
)
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
from neutrino_hub.modules.devices.wake_on_lan import send_magic_packet
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub import HUB_VERSION
from neutrino_hub.web.agent_tls import certificate_fingerprint
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.models import (
    DeviceAnnotation,
    DeviceClientErrorView,
    DeviceClientInfoView,
    DeviceCommandResultView,
    DeviceGpuView,
    DeviceListView,
    DeviceProcessView,
    DeviceEnrollmentRequest,
    DeviceEnrollmentView,
    DeviceInstallOrderView,
    DeviceInstallOutputView,
    DeviceModuleListView,
    DeviceModuleUpdate,
    DeviceModuleView,
    DeviceProcessKill,
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

POWER_ACTIONS = ("reboot", "shutdown")

# What the drawer draws while an order stands. The machine reports the same
# words once it starts; this is what covers the moment between the click and
# the beat that carries the order down.
_ORDER_STEP_STATES = {
    ORDER_ACTION_INSTALL: "installing",
    ORDER_ACTION_REMOVE: "removing",
    ORDER_ACTION_ENABLE: "enabling",
    ORDER_ACTION_DISABLE: "disabling",
}

LOGIN_KIND = "login"

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
        The view, carrying the platform on a device whose agent has beaten
        since the panel started.
    """
    key = device.mac_address.lower()
    view = _to_view(device, runtime.client_metrics.get(key))
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
        view.client.command_results = [
            DeviceCommandResultView(**outcome)
            for outcome in sorted(
                runtime.client_command_results.get(key, {}).values(),
                key=_outcome_finished_at,
                reverse=True,
            )
        ]
    return view


def _outcome_finished_at(outcome: dict) -> str:
    """When a stored command outcome arrived, for newest-first ordering."""
    return outcome.get("finished_at", "")


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
    ``password_id`` and ``sudo_password_id`` into the vault's stored logins —
    the sudo one for its password alone. No secret material passes through
    here.

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

    stored = {
        "host": ssh.host,
        "port": ssh.port,
        "username": ssh.username,
        "auth": ssh.auth,
    }
    if ssh.key_id:
        if not KeyRegistry().has_key(ssh.key_id):
            _refuse_unknown_credential("key_id")
        stored["key_id"] = ssh.key_id
    if ssh.password_id:
        if not _is_stored_login(ssh.password_id):
            _refuse_unknown_credential("password_id")
        stored["password_id"] = ssh.password_id
    if ssh.sudo_password_id:
        if not _is_stored_login(ssh.sudo_password_id):
            _refuse_unknown_credential("sudo_password_id")
        stored["sudo_password_id"] = ssh.sudo_password_id
    return stored


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
    for name, manifest in sorted(load_module_manifests().items()):
        status_ = reported.get(name, {})
        platforms = manifest.get("platforms", {})
        wanted = module_wish(device.client.modules.get(name))
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
                # With no platform reported yet, nothing is ruled out: the
                # agent will say what it cannot do once it beats.
                is_supported=(any(key in platforms for key in keys) if keys else True),
                is_enabled=wanted["is_enabled"],
                is_builtin=manifest.get("is_builtin", False),
                is_native=(entry == {} and not manifest.get("is_builtin", False)),
                has_activation=manifest.get("has_activation", False),
                is_activated=wanted["is_activated"],
                is_active=bool(status_.get("is_active")),
                state=state,
                code=code,
                params=params,
            )
        )
    return DeviceModuleListView(
        modules=modules,
        is_agent_managed=device.is_managed,
        is_agent_online=device.is_agent_online,
    )


@router.put("/{mac_address}/modules/{module}", response_model=DeviceModuleListView)
def set_module(
    mac_address: str,
    module: str,
    request: DeviceModuleUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeviceModuleListView:
    """Change what is wanted of one module on a device.

    Installing and activating are separate wishes and either can be sent on
    its own. The agent picks the change up on its next heartbeat and
    reconciles; this only records what should be true.

    Args:
        mac_address: The device.
        module: The module name.
        request: The wishes to change; absent ones are left alone.
        runtime: The shared runtime.

    Returns:
        The modules after the change.

    Raises:
        HTTPException: 404 for a module with no manifest.
    """
    manifests = load_module_manifests()
    if module not in manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown module"
        )
    key = mac_address.lower()
    device = DeviceRegistry().set_module(
        mac_address,
        module,
        is_enabled=request.is_enabled,
        is_activated=request.is_activated,
    )
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
    """IPv4 CIDRs of the device-facing interfaces.

    A served network's address is configuration; an exposed port on a
    ``server`` has whatever address the machine's own manager gave it, which
    only the live link can answer.

    Args:
        runtime: The shared runtime, for the network configuration.

    Returns:
        CIDR strings in configuration order, one per addressed interface.
    """
    reader = None
    cidrs = []
    for interface in runtime.network().device_facing_interfaces:
        if interface.is_lan and interface.lan.address:
            cidrs.append(interface.lan.cidr)
            continue
        if reader is None:
            reader = RouterLinkStatus()
        live = reader.link(interface.device_name).ipv4_address
        if live:
            cidrs.append(live)
    return cidrs


@router.post("/{mac_address}/kill_process")
async def kill_process(mac_address: str, request: DeviceProcessKill) -> dict:
    """End one process on a device, through sudo over SSH.

    Args:
        mac_address: The device's MAC.
        request: The process id to signal.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 400 for a pid no one should signal, or when the device
            has no SSH credentials; 502 when the device refuses.
    """
    if request.pid <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad pid")
    device = DeviceRegistry().get(mac_address)
    if not device.has_ssh:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no SSH credentials for this device",
        )
    operator = DeviceSshOperator(credentials=SshCredentials.from_dict(device.ssh or {}))
    code, output = await operator.run_privileged_once(f"kill {int(request.pid)}")
    if code != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=output or "the device refused the signal",
        )
    return {}


@router.post("/{mac_address}/action", response_model=TaskStarted)
async def start_action(
    mac_address: str,
    request: DeviceActionRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Start a long-running action on a device.

    The actions are ``install_client`` (over SSH), and ``reboot`` / ``shutdown``
    (queued for the agent when installed, otherwise run over SSH). Remote
    desktop has its own endpoints.

    Declared async deliberately: it schedules the background job on the running
    event loop, which a threadpool route would not have.

    Args:
        mac_address: The device's MAC.
        request: Which action to run.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from.

    Raises:
        HTTPException: 400 for an unknown action, or 409 when the device lacks
            the credentials or agent that action needs, or when the install
            pre-flight finds a device that is not Linux
            (``{"code": "unsupported_remote_install", "os": ...}``).
    """
    registry = DeviceRegistry()
    device = registry.get(mac_address)
    action = request.action

    # reboot and shutdown prefer the installed agent, which needs no shell
    # credentials, but fall back to SSH so an SSH-only device can still be
    # power-controlled.
    if action in POWER_ACTIONS:
        # An agent that is answering, not one that was installed once: the
        # flag stays true through a failed install and a stopped service, and
        # a command queued for an agent that never collects it is a machine
        # nobody rebooted and a task that ends "exit 0".
        if device.is_agent_online:
            runtime.queue_client_command(mac_address, {"id": action, "action": action})
            stream = runtime.tasks.start(
                label=f"{action} {mac_address}", source=_queued_message(action)
            )
            return TaskStarted(task_id=stream.id)
        if device.has_ssh:
            operator = DeviceSshOperator(
                credentials=SshCredentials.from_dict(device.ssh or {})
            )
            unit = "reboot" if action == "reboot" else "poweroff"
            stream = runtime.tasks.start(
                label=f"{action} {mac_address}",
                source=operator.run_privileged_stream(f"systemctl {unit}"),
            )
            return TaskStarted(task_id=stream.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{action} needs the agent or SSH credentials on this device",
        )

    if action != "install_client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown action {action!r}",
        )
    if not device.has_ssh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="installing the agent needs SSH credentials for this device",
        )

    operator = DeviceSshOperator(credentials=SshCredentials.from_dict(device.ssh or {}))
    # Pre-flight, refused before a task starts. A probe that failed — device
    # off, wrong credentials — is not a refusal: the task runs and its log
    # reports the failure, the same surface as every mid-install one.
    code, kernel = await operator.run_once("uname -s")
    if code == 0 and kernel and kernel != "Linux":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "unsupported_remote_install", "os": kernel},
        )
    packages = agent_packages()
    if not packages:
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
            operator.install_client(packages=packages, enrollment_link=link),
        ),
    )
    return TaskStarted(task_id=stream.id)


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
async def remote_desktop_status(mac_address: str) -> RemoteDesktopView:
    """Report what remote-desktop software is on a device.

    Args:
        mac_address: The device's MAC.

    Returns:
        AnyDesk and ToDesk state, each showing whether it is installed and
        running and, when it can be read, its session id to connect to.

    Raises:
        HTTPException: 409 when the device has no SSH credentials to probe with.
    """
    device = DeviceRegistry().get(mac_address)
    if not device.has_ssh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="reading remote-desktop status needs SSH credentials",
        )
    manager = RemoteDesktopManager(
        operator=DeviceSshOperator(
            credentials=SshCredentials.from_dict(device.ssh or {})
        )
    )
    return RemoteDesktopView(
        anydesk=_remote_desktop_view(await manager.status("anydesk")),
        todesk=_remote_desktop_view(await manager.status("todesk")),
    )


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
        product: Either ``anydesk`` or ``todesk``.
        request: The password to set.
        runtime: The shared runtime.

    Returns:
        A task id to stream the result from.

    Raises:
        HTTPException: 400 for an unknown product, 409 without SSH.
    """
    _, manager = _remote_desktop_manager(mac_address)
    # Checked here rather than caught from the call below: that is an async
    # generator, so calling it runs none of its body and the ValueError it
    # documents can never arrive. The refusal used to surface minutes later as
    # a failed task instead of as this 400.
    if product not in SUPPORTED_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown remote desktop product {product!r}; "
            f"expected one of {', '.join(SUPPORTED_PRODUCTS)}",
        )
    source = manager.set_password_stream(product, password=request.password)
    stream = runtime.tasks.start(
        label=f"set {product} password {mac_address}", source=source
    )
    return TaskStarted(task_id=stream.id)


def _remote_desktop_manager(mac_address: str):
    device = DeviceRegistry().get(mac_address)
    if not device.has_ssh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this needs SSH credentials for the device",
        )
    return device, RemoteDesktopManager(
        operator=DeviceSshOperator(
            credentials=SshCredentials.from_dict(device.ssh or {})
        )
    )


def _remote_desktop_view(status_: RemoteDesktopStatus) -> RemoteDesktopStatusView:
    return RemoteDesktopStatusView(
        product=status_.product,
        is_installed=status_.is_installed,
        is_running=status_.is_running,
        unreachable=status_.unreachable,
        session_id=status_.session_id,
        can_set_password=status_.can_set_password,
    )


async def _queued_message(action: str):
    yield f"[{action} queued; the agent runs it on its next heartbeat]\n"


def _to_view(device: ManagedDevice, metrics: dict | None = None) -> DeviceView:
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
            auth=device.ssh.get("auth", "key"),
            key_id=key_id,
            key_name=key_name,
            password_id=device.ssh.get("password_id"),
            sudo_password_id=device.ssh.get("sudo_password_id"),
        )
    is_agent_online = device.is_agent_online
    client_view = None
    if device.is_managed:
        latest = metrics or {}
        client_view = DeviceClientInfoView(
            is_managed=True,
            is_online=is_agent_online,
            version=device.client.version,
            is_version_mismatched=_is_version_mismatched(device.client.version),
            last_seen=device.client.last_seen,
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
