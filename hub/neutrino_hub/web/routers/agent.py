"""HTTP endpoints the neutrino_agent agents talk to.

These are the only routes without a session: agents authenticate with a
per-device token issued when the agent enrolled. They are served on the
agent channel's own TLS port, never on the panel's, and every enrollment
link carries the certificate fingerprint the agent pins.

Enrolling, leaving and fetching a package stay HTTP; everything live rides
the one socket in ``agent_ws``.
"""

import hashlib
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from neutrino_hub import HUB_VERSION
from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.clients.constants import CLIENT_ENROLLMENT_KIND
from neutrino_hub.modules.devices.constants import (
    AGENT_WIRE_GENERATION,
    DEVICE_MAC_PATTERN,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.utils.version_number import parse_version
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import (
    AgentEnroll,
    AgentEnrollReply,
    AgentLeave,
    ClientModulePackage,
    ClientPackageRequest,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/enroll", response_model=AgentEnrollReply)
def enroll(
    request: AgentEnroll,
    http_request: Request,
    runtime: PanelRuntime = Depends(get_runtime),
) -> AgentEnrollReply:
    """Let a machine introduce itself with an enrollment ticket.

    This is how a machine the gateway cannot reach — no SSH, or behind
    someone else's NAT — joins: its owner pastes a link into the agent's own
    page and the machine comes to the gateway rather than the other way
    round. A ticket generated for an already-known device binds to it; one
    generated blank creates a device keyed by the machine's own id.

    Args:
        request: The ticket and what the machine says it is.
        http_request: The connection, for where the machine is.
        runtime: The shared runtime, which holds the open tickets.

    Returns:
        The heartbeat token and the key the device is stored under.

    Raises:
        HTTPException: 401 when the ticket is unknown or has expired, 409
            when the agent is a later release than this hub — judged before
            the ticket so a refused machine has not spent the link.
    """
    _refuse_unadmitted(request.client_version, request.wire)
    # Taken before it is judged: a ticket leaves the store in one step, so
    # two machines racing the same link cannot both spend it.
    ticket = runtime.enrollments.pop(request.enrollment_token, None)
    if (
        ticket is None
        or ticket.get("kind") == CLIENT_ENROLLMENT_KIND
        or ticket["expires_at"] < time.time()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "enrollment_link_spent", "params": {}},
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
    address = peer_host(http_request)
    if address:
        runtime.client_address[key] = address
    return AgentEnrollReply(token=token, mac_address=key, hub_version=HUB_VERSION)


def version_refusal(
    client_version: str,
    wire: "int | None",
    *,
    code: str = "agent_newer_than_hub",
    version_field: str = "agent_version",
) -> "dict | None":
    """Judge whether an agent or a client may talk to this hub at all.

    The two ship together and are supported only together, so a newer agent
    is not negotiated with. The generation catches what a version compare
    cannot: a same-version rebuild that changed the shapes on the wire.

    Args:
        client_version: What the program reported itself as.
        wire: The generation the agent reported; None for a client, which
            carries none.
        code: The refusal code for a newer program.
        version_field: The params key the program's version is named under.

    Returns:
        ``{"code", "params"}`` naming the refusal, or None when the program
        is admitted. A version that does not parse on either side refuses
        nothing.
    """
    agent = parse_version(client_version)
    hub = parse_version(HUB_VERSION)
    if agent is not None and hub is not None and agent > hub:
        return {
            "code": code,
            "params": {"hub_version": HUB_VERSION, version_field: client_version},
        }
    if wire is None:
        return None
    if wire != AGENT_WIRE_GENERATION:
        return {
            "code": "agent_wire_stale",
            "params": {"hub_wire": AGENT_WIRE_GENERATION, "agent_wire": wire},
        }
    return None


def peer_host(request: Request) -> str:
    """Where a channel comes from, as this hub's own socket sees it.

    The one first-hand answer to where a machine is: a scan sees only the
    LANs this box serves, and a stored SSH host is a credential rather than
    a location. It follows the machine, because a beat from a new address
    is the machine at that address.

    Args:
        request: The agent's request.

    Returns:
        The peer's address, empty when the transport names none.
    """
    client = request.client
    return client.host if client is not None else ""


def _reported_key(registry: DeviceRegistry, request: AgentEnroll) -> str:
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
def leave(report: AgentLeave, runtime: PanelRuntime = Depends(get_runtime)) -> dict:
    """Accept an agent's word that it is leaving.

    Called when someone disconnects a machine from its own agent window. The
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
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "client_token_unknown", "params": {}},
        )
    registry.forget_client(device.mac_address)
    runtime.forget_client_state(device.mac_address)
    return {}


@router.post("/package")
def package(
    request: ClientPackageRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> Response:
    """Hand an agent the package for its family and machine.

    This is how an older agent updates itself: the reply's ``hub_version``
    tells it to move, and this hands it the same build an SSH install would
    deliver, over the same pinned channel its heartbeats use.

    The package carries an interpreter, so it is for one architecture. The
    agent names its own; a build that predates the field is answered from the
    platform its last heartbeat reported.

    Args:
        request: The token, the package family, and the machine.
        runtime: The shared runtime, which holds what each device reported.

    Returns:
        The package bytes, with their SHA-256 in ``X-Checksum-Sha256``.

    Raises:
        HTTPException: 401 when the token matches no device, 409 with the
            typed reason when the package cannot be produced — no build for
            that platform, or a release that did not serve what it pinned.
    """
    device = DeviceRegistry().find_by_client_token(request.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "client_token_unknown", "params": {}},
        )
    architecture = request.architecture or runtime.client_platform.get(
        device.mac_address, {}
    ).get("arch", "")
    try:
        path = runtime.agent_packages.package(
            family=request.family, architecture=architecture
        )
    except AgentArtifactFetchError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "params": error.params},
        ) from error
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-Checksum-Sha256": hashlib.sha256(data).hexdigest()},
    )


@router.post("/module_package")
def module_package(
    request: ClientModulePackage, runtime: PanelRuntime = Depends(get_runtime)
) -> Response:
    """Hand a machine the bytes an order named.

    The hub fetched these once for every device of this platform; this is
    only the handing down, over the channel the agent already trusts. The
    bytes travel here rather than on the heartbeat so a beat stays a beat.

    Args:
        request: The token and the artifact key the order carried.
        runtime: The shared runtime, which holds the cache.

    Returns:
        The package bytes, with their SHA-256 in ``X-Checksum-Sha256``.

    Raises:
        HTTPException: 401 when the token matches no device, 409 with the
            typed reason when the artifact cannot be produced — a key no
            manifest resolves to, or a fetch the vendor refused.
    """
    device = DeviceRegistry().find_by_client_token(request.token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "client_token_unknown", "params": {}},
        )
    try:
        artifact = runtime.agent_modules.artifact_for_key(
            request.artifact_key,
            sources=load_module_manifests(),
            platform=runtime.client_platform.get(device.mac_address, {}),
        )
        data = artifact.path.read_bytes()
    except AgentArtifactFetchError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "params": error.params},
        ) from error
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "module_artifact_missing", "params": {}},
        ) from error
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-Checksum-Sha256": hashlib.sha256(data).hexdigest()},
    )


def _refuse_unadmitted(client_version: str, wire: int) -> None:
    """Turn away an agent :func:`version_refusal` refuses.

    Args:
        client_version: What the agent reported itself as.
        wire: The generation the agent reported.

    Raises:
        HTTPException: 409 carrying the refusal.
    """
    refusal = version_refusal(client_version, wire)
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
