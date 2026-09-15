"""The Devices page: LAN discovery, annotations, and remote actions."""

import asyncio
import base64
import codecs
import ipaddress
import json
import secrets
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_ROLE_AGENT,
    CHANNEL_STREAM_COMMAND,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_COMMAND_TIMEOUT_S,
    DEVICE_MODULE_STATE_ABSENT,
    DEVICE_RDP_MODULE,
    DEVICE_REMOTE_DESKTOP_PRODUCTS,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.devices.lan_scan import LanScanner
from neutrino_hub.modules.devices.ssh_ops import (
    DeviceSshOperator,
    SshCredentials,
    login_password,
)
from neutrino_hub.modules.devices.wake_on_lan import send_magic_packet
from neutrino_hub.modules.router.link_status import device_addresses
from neutrino_hub.system.machine import machine_id
from neutrino_hub import HUB_VERSION
from neutrino_hub.web.agent_tls import certificate_fingerprint
from neutrino_hub.web.channel_serve import module_task_label
from neutrino_hub.web.constants import (
    WEB_REINSTALL_POLL_S,
    WEB_REINSTALL_REPORT_TIMEOUT_S,
    WEB_REINSTALL_RETURN_TIMEOUT_S,
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_EVENT_DEVICES,
    WEB_EVENT_DEVICE_REPORT,
    WEB_TASK_LABEL_AGENT_INSTALL,
)
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK
from neutrino_hub.web.models import (
    DeviceAgentInstallRequest,
    DeviceAnnotation,
    DeviceClientErrorView,
    DeviceClientInfoView,
    DeviceGpuView,
    DeviceListView,
    DeviceOnlineListView,
    DeviceOnlineView,
    DeviceProcessView,
    DeviceRdpView,
    DeviceEnrollmentRequest,
    DeviceEnrollmentView,
    DeviceInstallOutputView,
    DeviceInstallTaskView,
    DeviceProcessKill,
    DeviceRequest,
    DeviceServicesView,
    DeviceSshConfig,
    DeviceView,
    RemoteDesktopPassword,
    RemoteDesktopStatusView,
    RemoteDesktopView,
    TaskStarted,
    WolResult,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/hub/device", tags=["device"], dependencies=[Depends(require_session)]
)

# The agent's own verbs this page opens a ``command {module: agent}`` for.
AGENT_VERB_REBOOT = "reboot"
AGENT_VERB_SHUTDOWN = "shutdown"
AGENT_VERB_REINSTALL = "reinstall"
AGENT_VERB_KILL = "kill"
AGENT_VERB_REMOTE_DESKTOP_READ = "remote_desktop_read"
AGENT_VERB_REMOTE_DESKTOP_PASSWORD_SET = "remote_desktop_password_set"  # scan: allow
# The code the agent's report carries for a reinstall that did not take.
CODE_REINSTALL_FAILED = "reinstall_failed"

LOGIN_KIND = "login"
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
    registry = DeviceRegistry()
    own_machine = machine_id()
    rows = []
    for key in runtime.agent_sessions.keys():
        device = registry.get(key)
        if device is None:
            continue
        rows.append(
            DeviceOnlineView(
                device_id=key,
                name=device.name or runtime.device_hostname.get(key, "") or key,
                hostname=runtime.device_hostname.get(key, ""),
                platform=dict(runtime.device_platform.get(key, {})),
                is_hub=bool(own_machine) and device.machine_id == own_machine,
            )
        )
    rows.sort(key=_hub_first)
    return DeviceOnlineListView(devices=rows)


def _hub_first(row: DeviceOnlineView) -> tuple:
    """Sort the hub box's own device first, then by name."""
    return (not row.is_hub, row.name.lower())


def _device_list(runtime: PanelRuntime, *, is_active: bool) -> DeviceListView:
    scanner = LanScanner(lan_interfaces=runtime.network().lan_device_names)
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
    key = device.id
    view = _to_view(
        device,
        runtime.device_metrics.get(key),
        is_agent_online=runtime.agent_sessions.is_online(key),
        version=runtime.agent_sessions.version_of(key),
        last_seen=runtime.agent_sessions.last_seen_at(key),
        last_report_at=runtime.agent_sessions.last_report_at(key),
    )
    # Where its channel comes from wins over a scan: an agent on the overlay
    # is on no served LAN, and a machine that moved is at its new address a
    # beat later.
    view.ipv4_address = runtime.device_address.get(key) or view.ipv4_address
    platform = runtime.device_platform.get(key, {})
    if view.client is not None:
        view.client.platform_os = platform.get("os") or None
        view.client.platform_arch = platform.get("arch") or None
        view.client.hostname = runtime.device_hostname.get(key) or None
        error = runtime.device_last_error.get(key)
        if error is not None:
            view.client.last_error = DeviceClientErrorView(
                code=error.get("code", ""), params=error.get("params", {})
            )
        view.client.rdp = _rdp_view(runtime, key)
    return view


def _rdp_view(runtime: PanelRuntime, key: str) -> DeviceRdpView:
    """What one machine last said about sharing its desktop.

    Args:
        runtime: The shared runtime, which holds every declared share.
        key: The device.

    Returns:
        The share as the machine declared it, and whether its agent package
        carries the host at all. Only a machine reporting the host absent
        reads unavailable: one nobody has heard from says nothing either way.
    """
    reported = (runtime.device_modules.get(key) or {}).get(DEVICE_RDP_MODULE)
    state = str(reported.get("state", "")) if isinstance(reported, dict) else ""
    view = DeviceRdpView(is_available=state != DEVICE_MODULE_STATE_ABSENT)
    for share in runtime.device_shares.live():
        if share.device_id != key:
            continue
        view.is_shared = True
        view.account = share.account
        view.port = share.port
        view.attention = share.attention
        view.connected_count = share.connected_count
        break
    return view


@router.post("/set", response_model=DeviceView)
def annotate(
    annotation: DeviceAnnotation,
    runtime: PanelRuntime = Depends(get_runtime),
) -> DeviceView:
    """Name a device or give it SSH credentials.

    A scan row named here becomes a stored device under an id of its own.

    Args:
        annotation: The device, and the fields to change.
        runtime: The shared runtime.

    Returns:
        The device after the change, with no secret echoed back. It carries the
        metrics its agent last reported, like every other view of a device:
        built without them, the tile the page redraws from this reads as a
        machine that has gone offline until the next poll.

    Raises:
        HTTPException: 404 when no device has the id, 400 when the SSH
            block references a credential that is not stored.
    """
    device_id = annotation.device_id
    registry = DeviceRegistry()
    _require_device(registry, device_id)
    payload = annotation.model_dump(exclude_unset=True, exclude={"device_id"})
    if "ssh" in payload:
        payload["ssh"] = _store_ssh_secrets(annotation.ssh)
    device = registry.annotate(device_id, payload)
    runtime.events.publish(WEB_EVENT_DEVICES)
    return _device_view(runtime, device)


@router.post("/remove")
def forget(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Drop a device's row and everything held about it.

    The SSH key it referenced is left in the registry: keys outlive the
    devices that use them, and the Credentials page is where they are
    removed. What is held in memory goes with the record.

    Args:
        request: The device.
        runtime: The shared runtime, for what it holds about this device.

    Returns:
        An empty object.
    """
    device_id = request.device_id
    DeviceRegistry().forget(device_id)
    runtime.forget_device(device_id)
    runtime.events.publish(WEB_EVENT_DEVICES)
    return {}


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
    if ssh.sudo_login_id and not _is_stored_login(ssh.sudo_login_id):
        _refuse_unknown_credential("sudo_login_id")
    return {
        "host": ssh.host,
        "port": ssh.port,
        "username": ssh.username,
        "auth": ssh.auth,
        "key_id": ssh.key_id or None,
        "login_id": ssh.login_id or None,
        "sudo_login_id": ssh.sudo_login_id or None,
    }


def _is_stored_login(login_id: str) -> bool:
    record = SecretVault().get(login_id)
    return record is not None and record.kind == LOGIN_KIND


def _refuse_unknown_credential(field: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "unknown_credential", "params": {"field": field}},
    )


@router.post("/wake", response_model=WolResult)
def wake(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> WolResult:
    """Broadcast a Wake-on-LAN packet to a device, on its most recent link MAC.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        Whether the packet was sent. Delivery says nothing about whether the
        target actually wakes: that needs Wake-on-LAN armed in its firmware and
        its NIC, which the panel cannot verify from here.

    Raises:
        HTTPException: 404 when no device has the id, 409 ``wol_no_mac``
            when the device has never reported a MAC.
    """
    device_id = request.device_id
    device = _require_device(DeviceRegistry(), device_id)
    if not device.link_mac:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "wol_no_mac", "params": {"device_id": device_id}},
        )
    # A magic packet reaches only its own broadcast domain, and which of the
    # gateway's networks the sleeping device is on is exactly what cannot be
    # known while it is asleep. So send one to each; they are 102 bytes. Not
    # to an overlay: a tunnel has no broadcast domain, and its device refuses
    # the packet rather than dropping it.
    targets = []
    for interface in runtime.network().lan_interfaces:
        if not interface.lan.address:
            continue
        try:
            subnet = ipaddress.ip_network(interface.lan.cidr, strict=False)
        except ValueError:
            continue
        targets.append(str(subnet.broadcast_address))
    if not targets:
        return WolResult(is_sent=False, message="no served network has an address")

    sent = []
    failures = []
    for target in targets:
        try:
            send_magic_packet(device.link_mac, broadcast_address=target)
        except (ValueError, OSError) as error:
            failures.append(f"{target}: {error}")
            continue
        sent.append(target)
    if not sent:
        return WolResult(is_sent=False, message="; ".join(failures))
    return WolResult(
        is_sent=True,
        message=f"magic packet sent to {', '.join(sent)}",
    )


@router.post("/enrollment/create", response_model=DeviceEnrollmentView)
def create_enrollment(
    request: DeviceEnrollmentRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceEnrollmentView:
    """Generate a link a machine can join the gateway with.

    For machines the gateway cannot reach first — a Windows laptop, anything
    behind someone else's NAT. The owner installs the agent, opens its local
    page, and pastes this; nothing else is configured by hand.

    Args:
        request: An optional name, and an existing device to bind to; a scan
            row becomes a stored device under an id of its own.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The link, its token, and how long it lasts.

    Raises:
        HTTPException: 404 when no device has the id, 400 when no served
            network has an address, so there is nothing for a machine to
            reach the panel at.
    """
    device_id = None
    if request.device_id:
        registry = DeviceRegistry()
        _require_device(registry, request.device_id)
        device_id = registry.adopt(request.device_id).id
    link, token = _generate_enrollment_link(
        runtime, name=request.name, device_id=device_id
    )
    runtime.events.publish(WEB_EVENT_DEVICES)
    return DeviceEnrollmentView(link=link, token=token, expires_in_s=ENROLLMENT_TTL_S)


def _generate_enrollment_link(
    runtime: PanelRuntime, *, name: str, device_id: "str | None"
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
        device_id: The stored device to bind to, or None for any machine.

    Returns:
        The link and its ticket.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at; 409 with
            ``{"code": "agent_tls_missing"}`` when the channel has no
            certificate to pin.
    """
    urls, fingerprint = enrollment_link_parts(runtime)
    # One open invitation at a time: generating replaces whatever device link
    # was out, so only the machine the link was just made for can join on it.
    clear_enrollments(runtime, kind=None)
    token = secrets.token_urlsafe(ENROLLMENT_TOKEN_BYTES)
    runtime.enrollments[token] = {
        "name": name.strip(),
        "device_id": device_id or None,
        "expires_at": time.time() + ENROLLMENT_TTL_S,
    }
    return enrollment_link(urls, token, fingerprint), token


def enrollment_link_parts(runtime: PanelRuntime) -> tuple[list, str]:
    """What every enrollment link carries besides its ticket.

    Args:
        runtime: The shared runtime.

    Returns:
        The agent channel's URLs and the certificate fingerprint.

    Raises:
        HTTPException: 400 when no served network has an address, so there is
            nothing for a machine to reach the panel at; 409 with
            ``{"code": "agent_tls_missing"}`` when the channel has no
            certificate to pin.
    """
    urls = _agent_urls(runtime)
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "no_reachable_address", "params": {}},
        )
    try:
        fingerprint = certificate_fingerprint()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_tls_missing", "params": {}},
        ) from error
    return urls, fingerprint


def enrollment_link(
    urls: list, token: str, fingerprint: str, *, role: str = CHANNEL_ROLE_AGENT
) -> str:
    """The link a ticket rides in.

    Args:
        urls: The agent channel's URLs.
        token: The ticket.
        fingerprint: The certificate fingerprint the program pins.
        role: Who the link is for, ``agent`` or ``client``.

    Returns:
        The ``neutrino://enroll/`` link.
    """
    body = {"urls": urls, "token": token, "fp": fingerprint, "role": role}
    # The whole payload rides base64url, whose alphabet has no character a
    # shell splits or a URL escapes — the link pastes anywhere unquoted.
    payload = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    return f"neutrino://enroll/{payload.rstrip('=')}"


def clear_enrollments(runtime: PanelRuntime, *, kind: "str | None") -> None:
    """Drop every open ticket of one kind.

    Args:
        runtime: The shared runtime.
        kind: The ticket kind to drop; None drops the device tickets.
    """
    for token in [
        token
        for token, ticket in runtime.enrollments.items()
        if ticket.get("kind") == kind
    ]:
        runtime.enrollments.pop(token, None)


@router.get("/service", response_model=DeviceServicesView)
def list_services(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceServicesView:
    """Read one device's services: the catalog it is served, and its rows.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime, for what the agent last reported.

    Returns:
        The view; empty entries mean the device has not beaten since the
        panel started.

    Raises:
        HTTPException: 404 when no device has the id.
    """
    key = _require_device(DeviceRegistry(), device_id).id
    entries: list = []
    scope = runtime.device_scope.get(key)
    if scope is not None:
        catalog, _ = runtime.device_catalog.catalog(
            scope=scope, platform=runtime.device_platform.get(key, {})
        )
        entries = list(catalog.get("services", []))
    return DeviceServicesView(
        accounts=list(runtime.device_accounts.get(key, [])), entries=entries
    )


@router.get("/install_output", response_model=DeviceInstallOutputView)
def install_output(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceInstallOutputView:
    """Every install this device has run, whatever asked for it.

    One pane, because a person reading why something is not on a machine
    should not have to know which surface started it: the agent's own
    install over SSH, and each module's install or uninstall, whose lines
    the agent sent up a ``log`` stream.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime, which holds the tasks.

    Returns:
        The device's install tasks since the panel started, newest first,
        each with what it printed.
    """
    manifests = load_module_manifests()
    tasks = []
    for stream in reversed(runtime.tasks.streams()):
        module = _task_module(stream.label, device_id)
        if module is None:
            continue
        tasks.append(
            DeviceInstallTaskView(
                task_id=stream.id,
                module=module,
                title=manifests.get(module, {}).get("title", module),
                is_finished=stream.is_finished,
                exit_code=stream.exit_code,
                output="".join(stream.buffer),
                started_at=stream.started_at,
                finished_at=stream.finished_at,
            )
        )
    return DeviceInstallOutputView(tasks=tasks)


def _task_module(label: str, device_id: str) -> "str | None":
    """The module a task label names on one device.

    Args:
        label: The task's label.
        device_id: The device.

    Returns:
        The module name, empty for the agent's own install, or None for a
        task that is not an install on this device.
    """
    if label == WEB_TASK_LABEL_AGENT_INSTALL.format(device_id=device_id):
        return ""
    prefix = module_task_label(device_id, "")
    if label.startswith(prefix):
        return label[len(prefix) :]
    return None


def _require_device(registry: DeviceRegistry, device_id: str) -> ManagedDevice:
    """The device an id names.

    Args:
        registry: The stored devices.
        device_id: What the request named: a stored id or a ``scan:<mac>`` id.

    Returns:
        The device.

    Raises:
        HTTPException: 404 ``device_unknown`` when no device has the id.
    """
    device = registry.get(device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "device_unknown", "params": {"device_id": device_id}},
        )
    return device


def _agent_urls(runtime: PanelRuntime) -> list:
    """Every address a machine could be told to reach the agent channel on.

    The set is the firewall's: every exposed interface, whatever its role,
    and every exposed overlay. A served network contributes its configured
    address, everything else the address the live link holds. All of them,
    not one: only one is on the joining machine's network, and neither the
    hub nor the person pasting the link knows which.

    Args:
        runtime: The shared runtime, for the network configuration and the
            port.

    Returns:
        Base ``https`` URLs, in configuration order, one per address.
    """
    port = runtime.settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT)
    network = runtime.network()
    configured = {
        interface.device_name: interface.lan.address
        for interface in network.lan_interfaces
        if interface.lan.address
    }
    live = None
    urls = []
    for name in network.exposed_interfaces:
        address = configured.get(name, "")
        if not address:
            if live is None:
                live = device_addresses()
            address = live.get(name, "").split("/")[0]
        url = f"https://{address}:{port}"
        if address and url not in urls:
            urls.append(url)
    return urls


@router.post("/process/kill")
def kill_process(
    request: DeviceProcessKill,
    runtime: PanelRuntime = Depends(get_runtime),
) -> dict:
    """End one process on a device, through its agent.

    Args:
        request: The device, and the process id to signal.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 400 for a pid no one should signal, 404 when no such
            process runs or no device has the id, 409 when the agent is not
            answering, 502 when the device refused the signal.
    """
    if request.pid <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "kill_failed", "params": {"pid": request.pid}},
        )
    key = _require_device(DeviceRegistry(), request.device_id).id
    info = _run_device_command(runtime, key, AGENT_VERB_KILL, {"pid": request.pid})
    code = str(info.get("code", "") or "")
    params = dict(info.get("params") or {})
    if code == "process_missing":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": code, "params": params},
        )
    if code or int(params.get("exit_code", 1) or 0) != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": code or "kill_failed", "params": params},
        )
    return {}


def _command_args(verb: str, args: "dict | None" = None) -> dict:
    """What a ``command`` stream's open carries for one of the agent's verbs."""
    return {"module": CHANNEL_COMMAND_MODULE_AGENT, "verb": verb, **dict(args or {})}


def _run_device_command(runtime: PanelRuntime, key: str, verb: str, args: dict):
    """Run one of the agent's verbs on a device and wait for its close.

    Args:
        runtime: The shared runtime.
        key: The device.
        verb: The verb.
        args: The verb's arguments.

    Returns:
        The close, ``{"code", "params"}``.

    Raises:
        HTTPException: 409 with the code when the device has no channel or
            did not answer in time.
    """
    try:
        return runtime.agent_sessions.run_stream_from_thread(
            key,
            CHANNEL_STREAM_COMMAND,
            _command_args(verb, args),
            timeout=DEVICE_MODULE_COMMAND_TIMEOUT_S,
        )
    except (AgentOfflineError, StreamRefusedError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "params": dict(error.params)},
        ) from error


@router.post("/agent/install", response_model=TaskStarted)
async def install_agent(
    request: DeviceAgentInstallRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Put the agent on a machine over SSH, as a task.

    Declared async deliberately: it schedules the background job on the running
    event loop, which a threadpool route would not have.

    Args:
        request: The device, which as a scan row becomes a stored device
            under an id of its own, and how to reach the machine.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from; the one already running
        on this device, when an install is under way.

    Raises:
        HTTPException: 404 when no device has the id, 400 for an install
            naming no single credential, 409 when the install's pre-flight
            finds a device that is not Linux
            (``{"code": "unsupported_remote_install", "os": ...}``) or the
            hub carries no agent package.
    """
    device = _require_device(DeviceRegistry(), request.device_id)
    label = WEB_TASK_LABEL_AGENT_INSTALL.format(device_id=device.id)
    running = runtime.tasks.running(label)
    if running is not None:
        return TaskStarted(task_id=running.id)
    device, credentials = await asyncio.to_thread(_install_credentials, device, request)
    operator = DeviceSshOperator(credentials=credentials)
    # Pre-flight, refused before a task starts. A probe that failed — device
    # off, wrong credentials — is not a refusal: the task runs and its log
    # reports the failure, the same surface as every mid-install one.
    code, kernel = await operator.run_once("uname -s")
    if code == 0 and kernel and kernel != "Linux":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "unsupported_remote_install", "params": {"os": kernel}},
        )
    packages = runtime.agent_packages
    if not packages.has_packages():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_package_missing", "params": {}},
        )
    # A ticket, not a heartbeat token: the install walks the same enrollment
    # path a pasted link does, and a failed install leaves any live agent
    # beating exactly as it was.
    link, _ = _generate_enrollment_link(
        runtime, name=device.name or "", device_id=device.id
    )
    stream = runtime.tasks.start(
        label=label,
        source=operator.install_client(
            packages=packages,
            enrollment_link=link,
            sudo_password=_sudo_material(request),
        ),
    )
    runtime.events.publish(WEB_EVENT_DEVICES)
    return TaskStarted(task_id=stream.id)


@router.post("/agent/reinstall", response_model=TaskStarted)
async def reinstall_agent(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> TaskStarted:
    """Have a device's agent install itself again, as a task.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from.

    Raises:
        HTTPException: 404 when no device has the id, 409 with
            ``agent_offline`` when the device has no live agent.
    """
    key = _require_online(runtime, request.device_id)
    return _start_task(
        runtime, f"{AGENT_VERB_REINSTALL} {key}", _reinstall_stream(runtime, key)
    )


@router.post("/reboot", response_model=TaskStarted)
async def reboot(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> TaskStarted:
    """Reboot a device through its agent, as a task.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from.

    Raises:
        HTTPException: 404 when no device has the id, 409 with
            ``agent_offline`` when the device has no live agent.
    """
    return _start_agent_command(runtime, request.device_id, AGENT_VERB_REBOOT)


@router.post("/shutdown", response_model=TaskStarted)
async def shutdown(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> TaskStarted:
    """Shut a device down through its agent, as a task.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        A task id the browser streams output from.

    Raises:
        HTTPException: 404 when no device has the id, 409 with
            ``agent_offline`` when the device has no live agent.
    """
    return _start_agent_command(runtime, request.device_id, AGENT_VERB_SHUTDOWN)


def _start_agent_command(
    runtime: PanelRuntime, device_id: str, verb: str
) -> TaskStarted:
    """Run one of the agent's verbs on a device's live agent as a task.

    Args:
        runtime: The shared runtime.
        device_id: The device.
        verb: The verb.

    Returns:
        The task started.

    Raises:
        HTTPException: 404 when no device has the id, 409 with
            ``agent_offline`` when the device has no live agent.
    """
    key = _require_online(runtime, device_id)
    return _start_task(
        runtime, f"{verb} {key}", _agent_command_stream(runtime, key, verb)
    )


def _require_online(runtime: PanelRuntime, device_id: str) -> str:
    """The key of a device whose agent holds a socket.

    Args:
        runtime: The shared runtime.
        device_id: The device.

    Returns:
        The device's key.

    Raises:
        HTTPException: 404 when no device has the id, 409 with
            ``agent_offline`` when the device has no live agent.
    """
    key = _require_device(DeviceRegistry(), device_id).id
    if not runtime.agent_sessions.is_online(key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_offline", "params": {}},
        )
    return key


def _start_task(runtime: PanelRuntime, label: str, source) -> TaskStarted:
    """Start one task the browser streams, and say the device list moved."""
    stream = runtime.tasks.start(label=label, source=source)
    runtime.events.publish(WEB_EVENT_DEVICES)
    return TaskStarted(task_id=stream.id)


def _install_credentials(
    device: ManagedDevice, request: DeviceAgentInstallRequest
) -> tuple:
    """Store the install's SSH block and open the credentials it names.

    Exactly one credential source is taken: a stored key, a stored login,
    or a password typed now. A typed password is stored as a vault login
    only when asked, and the device's block records the id. The sudo
    password is not looked at here and is written nowhere.

    Args:
        device: The device being installed on; a scan row is stored under
            an id of its own.
        request: The install request.

    Returns:
        ``(device, credentials)``: the stored device, and the credentials
        the install connects with.

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
            except ValueError as error:
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
                sudo_login_id=request.sudo_login_id or None,
            )
        )
        device = DeviceRegistry().annotate(device.id, {"ssh": stored})
    credentials = SshCredentials.from_dict(stored)
    if request.password:
        credentials.password = request.password
    return device, credentials


def _sudo_material(request: DeviceAgentInstallRequest) -> "str | None":
    """The password sudo is fed on the device for this install.

    Args:
        request: The install request.

    Returns:
        The referenced vault login's password, else the one typed for this
        install, else None for passwordless sudo.

    Raises:
        HTTPException: 400 when ``sudo_login_id`` names no vault login.
    """
    if request.sudo_login_id:
        material = login_password(request.sudo_login_id)
        if material is None:
            _refuse_unknown_credential("sudo_login_id")
        return material
    return request.sudo_password or None


@router.get("/remote_desktop", response_model=RemoteDesktopView)
def remote_desktop_status(
    device_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> RemoteDesktopView:
    """Report what remote-desktop software is on a device.

    AnyDesk and TeamViewer are read by the agent on request; RustDesk is a
    module this hub installs, and its id rides the report with that
    module's block, so a device whose agent is quiet still shows it.

    Args:
        device_id: The device, from the query.
        runtime: The shared runtime.

    Returns:
        Each agent-read product's state, and RustDesk's id when the machine
        has reported one.

    Raises:
        HTTPException: 404 when no device has the id.
    """
    key = _require_device(DeviceRegistry(), device_id).id
    cards = {}
    for product in DEVICE_REMOTE_DESKTOP_PRODUCTS:
        try:
            info = runtime.agent_sessions.run_stream_from_thread(
                key,
                CHANNEL_STREAM_COMMAND,
                _command_args(AGENT_VERB_REMOTE_DESKTOP_READ, {"product": product}),
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
    params = info.get("params") if isinstance(info.get("params"), dict) else {}
    result = params.get("result") if isinstance(params.get("result"), dict) else {}
    session_id = result.get("session_id")
    return RemoteDesktopStatusView(
        product=product,
        is_installed=bool(result.get("is_installed")),
        is_running=bool(result.get("is_running")),
        session_id=str(session_id) if session_id else None,
        can_set_password=bool(result.get("can_set_password", True)),
    )


def _reported_rustdesk_id(runtime: PanelRuntime, device_id: str) -> str:
    """The RustDesk id one machine's module report carries.

    Args:
        runtime: The shared runtime.
        device_id: The device.

    Returns:
        The id, empty when the machine has not reported one.
    """
    status_ = (runtime.device_modules.get(device_id) or {}).get("rustdesk")
    if not isinstance(status_, dict):
        return ""
    details = status_.get("details")
    if not isinstance(details, dict):
        return ""
    return str(details.get("rustdesk_id", "") or "")


@router.post("/remote_desktop/password/set", response_model=TaskStarted)
async def set_remote_desktop_password(
    request: RemoteDesktopPassword,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TaskStarted:
    """Set a product's unattended-access password on a device.

    Args:
        request: The device, one of ``DEVICE_REMOTE_DESKTOP_PRODUCTS``, and
            the password to set.
        runtime: The shared runtime.

    Returns:
        A task id to stream the result from.

    Raises:
        HTTPException: 400 for an unknown product, 404 when no device has
            the id, 409 when the agent is not answering.
    """
    device_id = request.device_id
    product = request.product
    if product not in DEVICE_REMOTE_DESKTOP_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "product_unknown", "params": {"product": product}},
        )
    key = _require_device(DeviceRegistry(), device_id).id
    if not runtime.agent_sessions.is_online(key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_offline", "params": {}},
        )
    stream = runtime.tasks.start(
        label=f"set {product} password {key}",
        source=_agent_command_stream(
            runtime,
            key,
            AGENT_VERB_REMOTE_DESKTOP_PASSWORD_SET,
            {"product": product, "password": request.password},
        ),
    )
    return TaskStarted(task_id=stream.id)


@router.post("/desktop/seat_password/reset")
def reset_seat_password(
    request: DeviceRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Give one device a fresh seat password and hand it down.

    Nobody types this password and nobody is shown it: the hub generates it,
    seals it under the vault's data key, and the machine reads it out of the
    state it is pushed. Every viewer connected on the old one must dial
    again.

    Args:
        request: The device.
        runtime: The shared runtime.

    Returns:
        An empty object.

    Raises:
        HTTPException: 404 when no device has the id, 409 ``agent_offline``
            when the device has no channel, 502 when its socket did not take
            the state in time.
    """
    key = _require_device(DeviceRegistry(), request.device_id).id
    if not runtime.agent_sessions.is_online(key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_offline", "params": {}},
        )
    runtime.desired_states.reset_seat_password(key)
    try:
        runtime.push_desired_state(key)
    except AgentOfflineError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "agent_offline", "params": {}},
        ) from error
    except StreamRefusedError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": error.code, "params": dict(error.params)},
        ) from error
    runtime.events.publish(WEB_EVENT_DEVICE_REPORT, key)
    return {}


async def _agent_command_stream(
    runtime: PanelRuntime, key: str, verb: str, args: "dict | None" = None
) -> AsyncIterator[str]:
    """Run one of the agent's verbs on a device, streaming what it prints.

    Args:
        runtime: The shared runtime, which holds the sockets.
        key: The device.
        verb: The verb.
        args: The verb's arguments.

    Yields:
        Each line the agent sends, then the close's output and its code.
    """
    try:
        stream = await runtime.agent_sessions.open_stream(
            key, CHANNEL_STREAM_COMMAND, _command_args(verb, args)
        )
    except AgentOfflineError as error:
        yield json.dumps({"code": error.code, "params": dict(error.params)}) + "\n"
        return
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        item = await stream.recv()
        if item is None:
            break
        yield decoder.decode(item[1])
    info = stream.close_info or {}
    params = info.get("params") or {}
    output = str(params.get("output", "") or "")
    if output:
        yield output if output.endswith("\n") else output + "\n"
    if info.get("code"):
        yield json.dumps({"code": info["code"], "params": params}) + "\n"
    elif "exit_code" in params:
        yield f"[exit {params['exit_code']}]\n"


async def _reinstall_stream(runtime: PanelRuntime, key: str) -> AsyncIterator[str]:
    """Reinstall a device's agent and report how it went.

    The agent hands the package to a transient unit on the machine and
    closes the command; the unit runs the package manager, which replaces
    and restarts the agent. The task follows the reports: the agent that
    returns and reports no ``reinstall_failed`` error was reinstalled, and
    an installer that failed without restarting anything reports that
    error on the socket that stayed.

    Args:
        runtime: The shared runtime, which holds the sockets.
        key: The device.

    Yields:
        The command's lines, the agent's return, then its exit status or
        the failure's code, or a typed word when nothing was reported.
    """
    before = runtime.agent_sessions.get(key)
    before_failure = _reinstall_failure(before)
    async for line in _agent_command_stream(runtime, key, AGENT_VERB_REINSTALL):
        if line.startswith("{"):
            yield line
            return
        yield line
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WEB_REINSTALL_RETURN_TIMEOUT_S
    reconnected_at = None
    while loop.time() < deadline:
        session = runtime.agent_sessions.get(key)
        if session is not None and session is not before and reconnected_at is None:
            reconnected_at = loop.time()
            yield f"agent {runtime.agent_sessions.version_of(key)} reconnected\n"
        failure = _reinstall_failure(session)
        if failure is not None and failure != before_failure:
            yield json.dumps({"code": CODE_REINSTALL_FAILED, "params": failure}) + "\n"
            return
        if reconnected_at is not None and session is not None and session.reported_at:
            yield "[exit 0]\n"
            return
        if (
            reconnected_at is not None
            and loop.time() - reconnected_at > WEB_REINSTALL_REPORT_TIMEOUT_S
        ):
            yield "reinstalled, no report from this agent\n"
            return
        await asyncio.sleep(WEB_REINSTALL_POLL_S)
    yield json.dumps({"code": "reinstall_not_reported", "params": {}}) + "\n"


def _reinstall_failure(session) -> "dict | None":
    """The ``reinstall_failed`` error a session's last report carries, if any.

    Args:
        session: The device's session, or None while it is offline.

    Returns:
        The error's params, ``{exit_code, finished_at}``, or None when the
        report carries no such error.
    """
    if session is None:
        return None
    error = session.report.get("error")
    if not isinstance(error, dict) or error.get("code") != CODE_REINSTALL_FAILED:
        return None
    params = error.get("params")
    return dict(params) if isinstance(params, dict) else {}


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
        id=device.id,
        machine_id=device.machine_id,
        mac_addresses=list(device.mac_addresses),
        link_mac=device.link_mac,
        ipv4_address=device.ipv4_address,
        name=device.name,
        icon=device.icon,
        vendor=device.vendor,
        # A beating agent is proof of reachability the ARP sweep cannot give:
        # a machine on the overlay has no neighbour entry on any LAN.
        is_online=device.is_online or is_agent_online,
        is_agent_online=is_agent_online,
        has_ssh=device.has_ssh,
        is_stored=device.is_stored,
        ssh=ssh_view,
        client=client_view,
    )


def _is_version_mismatched(agent_version: "str | None") -> bool:
    """Whether an agent is a different version from this hub.

    The two are released together and supported only together
    (skills/core-code-author/agent_work_rule/release.md), so any difference means the
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
