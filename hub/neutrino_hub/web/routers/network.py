"""The Network tab: what each interface is for, and what it is doing.

Every interface carries a role — uplink, served network, or unused — and saving
one applies it on its own. That is deliberate: an interface is the unit a person
thinks about here, and applying the whole page at once would mean a typo in the
Wi-Fi settings could take the wired LAN down with it.
"""

import asyncio
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.router.constants import (
    ROUTER_INTENTS,
    ROUTER_POLICIES,
    ROUTER_ROLE_DISABLED,
    ROUTER_ROLE_LAN,
    ROUTER_ROLE_SPLIT,
    ROUTER_ROLE_WAN,
    ROUTER_ROLES,
    ROUTER_VLAN_ID_MAX,
    ROUTER_VLAN_ID_MIN,
    ROUTER_WAN_METHOD_STATIC,
)
from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterNetworkConfig,
    RouterVlanSettings,
)
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_KIND_WIFI,
    LinkStatus,
    RouterLinkStatus,
)
from neutrino_hub.modules.router.routes import build_uplink_plan, remove_vlan_device
from neutrino_hub.modules.router.wifi import (
    AP_PASSPHRASE_MAX_LENGTH,
    AP_PASSPHRASE_MIN_LENGTH,
    RouterWifiRadio,
)
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    InterfaceLink,
    InterfaceSettings,
    InterfaceView,
    NetworkOptions,
    NetworkView,
    PlannedUplinkView,
    UpstreamLineView,
    WifiJoinRequest,
    WifiNetworkView,
    WifiScanView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/network", tags=["network"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=NetworkView)
def read_network(runtime: PanelRuntime = Depends(get_runtime)) -> NetworkView:
    """Read every interface's role beside its live state.

    Interfaces the box has but the config has never mentioned are included with
    the ``disabled`` role, so a newly plugged adapter shows up ready to be given
    a job rather than being invisible until someone edits JSON.

    Args:
        runtime: The shared runtime.

    Returns:
        The Network tab payload.
    """
    return _build_view(runtime)


@router.put("/options", response_model=NetworkView)
async def update_options(
    options: NetworkOptions, runtime: PanelRuntime = Depends(get_runtime)
) -> NetworkView:
    """Change the settings that belong to no single interface.

    Args:
        options: The new options.
        runtime: The shared runtime.

    Returns:
        The Network tab payload.

    Raises:
        HTTPException: 502 when the firewall reload fails.
    """
    if options.uplink_policy not in ROUTER_POLICIES:
        raise _bad_request(f"unknown uplink policy {options.uplink_policy!r}")
    network = runtime.network()
    network.is_ssh_from_wan_allowed = options.is_ssh_from_wan_allowed
    network.uplink_policy = options.uplink_policy
    network.is_inter_lan_allowed = options.is_inter_lan_allowed
    runtime.write_network(network)
    await _apply(runtime, only=None)
    return _build_view(runtime)


@router.put("/interfaces/{name}", response_model=NetworkView)
async def update_interface(
    name: str,
    settings: InterfaceSettings,
    runtime: PanelRuntime = Depends(get_runtime),
) -> NetworkView:
    """Set one interface's role and settings, and apply them.

    Applying is the point: the response means the interface is already doing
    this, not that the intent was filed. Changing the address of the LAN the
    request arrived on will drop the connection before the response can be
    written, which the page warns about beforehand.

    Args:
        name: Interface name from the path; the body must agree.
        settings: The interface's new configuration.
        runtime: The shared runtime.

    Returns:
        The Network tab payload.

    Raises:
        HTTPException: 400 when the settings are inconsistent, 502 when
            applying them fails.
    """
    if settings.name != name:
        raise _bad_request("the interface in the path and the body must match")

    network = runtime.network()
    saved = _to_interface(settings)
    link = RouterLinkStatus().link(saved.device_name)
    _validate(settings, link=link, network=network)

    # Leaving the split role takes the VLANs with it: they cannot exist
    # without the trunk, and the page has already asked about them.
    stored = network.interface(name)
    orphaned = []
    if stored is not None and stored.is_split and settings.role != ROUTER_ROLE_SPLIT:
        for child in network.vlan_children(name):
            network.remove(child.name)
            orphaned.append(child.name)

    network.replace(saved)
    if saved.is_split and network.untagged_child(name) is None:
        # Splitting makes the untagged traffic explicit: it becomes the main
        # entry, inheriting the role the port held so far — splitting an
        # uplink must not cost the uplink.
        was = stored.role if stored is not None else ROUTER_ROLE_LAN
        network.replace(
            RouterInterface(
                name=f"{name}.main",
                role=(
                    was
                    if was in (ROUTER_ROLE_WAN, ROUTER_ROLE_LAN)
                    else ROUTER_ROLE_DISABLED
                ),
                wan=saved.wan,
                lan=saved.lan,
                vlan=RouterVlanSettings(parent=name, id=None),
            )
        )
    if saved.is_wan and saved.wan.is_pinned_primary:
        network.keep_single_primary(name)
    runtime.write_network(network)
    for child_name in orphaned:
        await asyncio.to_thread(remove_vlan_device, child_name)
    await _apply(runtime, only=name)
    return _build_view(runtime)


@router.delete("/interfaces/{name}", response_model=NetworkView)
async def delete_interface(
    name: str, runtime: PanelRuntime = Depends(get_runtime)
) -> NetworkView:
    """Remove one VLAN interface, configuration and device together.

    Only VLANs can be deleted: a physical port is hardware, and the most the
    panel can say about hardware is ``disabled``.

    Args:
        name: Interface name from the path.
        runtime: The shared runtime.

    Returns:
        The Network tab payload.

    Raises:
        HTTPException: 404 for an unknown interface, 400 for a physical one,
            502 when applying the removal fails.
    """
    network = runtime.network()
    interface = network.interface(name)
    if interface is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name} is not a configured interface",
        )
    if interface.vlan is None:
        raise _bad_request(f"{name} is a physical interface; only VLANs are removable")
    if interface.is_untagged:
        raise _bad_request(
            "the untagged main belongs to the split port; change the port's "
            "role instead of removing it"
        )

    parent = interface.vlan.parent
    network.remove(name)
    runtime.write_network(network)
    await asyncio.to_thread(remove_vlan_device, name)
    only = parent if network.interface(parent) is not None else None
    await _apply(runtime, only=only)
    return _build_view(runtime)


@router.get("/interfaces/{name}/wifi/scan", response_model=WifiScanView)
def scan_wifi(name: str) -> WifiScanView:
    """Scan for the networks a wireless interface can see.

    Args:
        name: Interface name.

    Returns:
        What the scan found, strongest first.

    Raises:
        HTTPException: 400 when the interface is not wireless, 502 when the
            scan fails.
    """
    _require_wifi(name)
    try:
        networks = RouterWifiRadio(interface=name).scan()
    except CommandError as error:
        raise _bad_gateway(str(error)) from error
    return WifiScanView(
        networks=[
            WifiNetworkView(
                ssid=network.ssid,
                signal_percent=network.signal_percent,
                security=network.security,
                is_active=network.is_active,
                is_saved=network.is_saved,
            )
            for network in networks
        ]
    )


@router.post("/interfaces/{name}/wifi/join", response_model=NetworkView)
async def join_wifi(
    name: str,
    request: WifiJoinRequest,
    runtime: PanelRuntime = Depends(get_runtime),
) -> NetworkView:
    """Join a wireless network on an interface, and remember which one.

    Joining is a separate action from setting the role because it can fail on
    its own terms — a wrong passphrase should not roll back the role. The
    interface is put into the WAN role on success, since joining a network is
    only ever done to get an uplink from it.

    Args:
        name: Interface name.
        request: The network to join and, if needed, its passphrase.
        runtime: The shared runtime.

    Returns:
        The Network tab payload, with the interface's new address in it.

    Raises:
        HTTPException: 400 when the interface is not wireless, 502 when the
            association fails.
    """
    _require_wifi(name)
    try:
        RouterWifiRadio(interface=name).join(
            ssid=request.ssid, passphrase=request.passphrase
        )
    except CommandError as error:
        raise _bad_gateway(f"could not join {request.ssid}: {error}") from error

    network = runtime.network()
    interface = network.interface(name) or RouterInterface(name=name)
    interface.role = ROUTER_ROLE_WAN
    interface.wifi.ssid = request.ssid
    network.replace(interface)
    runtime.write_network(network)
    await _apply(runtime, only=name)
    return _build_view(runtime)


def _build_view(runtime: PanelRuntime) -> NetworkView:
    network = runtime.network()
    status_reader = runtime.link_status()
    links = {link.name: link for link in status_reader.all_links()}

    names = list(links)
    for interface in network.interfaces:
        if interface.name not in links:
            names.append(interface.name)
    # Tabs read left to right as the box is wired: each port, then what rides
    # on it — the untagged main first, then its VLANs by tag.
    physical_order = {name: index for index, name in enumerate(names)}
    names.sort(
        key=lambda name: _tab_order(
            network.interface(name) or RouterInterface(name=name), physical_order
        )
    )

    views = []
    for name in names:
        interface = network.interface(name) or RouterInterface(name=name)
        # The main entry has no device of its own; what it is doing is what
        # the trunk port is doing.
        link = links.get(interface.device_name, LinkStatus(name=name))
        views.append(
            InterfaceView(
                settings=_propose_lan(_to_settings(interface), network=network),
                link=InterfaceLink(
                    name=link.name,
                    kind=link.kind,
                    is_present=link.is_present,
                    is_up=link.is_up,
                    ipv4_address=link.ipv4_address,
                    mac_address=link.mac_address,
                    connection=link.connection,
                    ssid=link.ssid,
                    signal_percent=link.signal_percent,
                    speed_mbps=link.speed_mbps,
                    gateway=status_reader.gateway_for(interface.device_name),
                    is_ap_capable=link.is_ap_capable,
                ),
            )
        )
    plan = build_uplink_plan(network=network, status=status_reader)
    return NetworkView(
        interfaces=views,
        is_ssh_from_wan_allowed=network.is_ssh_from_wan_allowed,
        uplink_policy=network.uplink_policy,
        is_inter_lan_allowed=network.is_inter_lan_allowed,
        default_gateway=status_reader.default_gateway(),
        lines=[
            UpstreamLineView(
                id=line.id,
                gateway=line.gateway,
                is_shared=line.is_shared,
                is_carrying=line.is_carrying,
                members=[
                    PlannedUplinkView(
                        name=member.name,
                        rank=member.rank,
                        is_active=member.is_active,
                        route_metric=member.route_metric,
                        reason=member.reason,
                        speed_mbps=member.facts.speed_mbps,
                    )
                    for member in line.members
                ],
            )
            for line in plan.lines
        ],
        warnings=_warnings(views),
    )


def _warnings(views: list[InterfaceView]) -> list[str]:
    """Trouble the configuration is allowed to be in but should not stay in.

    These are live conditions, not invalid settings — which is why they warn
    rather than block. The one that matters is two of the box's own interfaces
    sitting on one subnet: whether that happens is decided by whatever DHCP
    server is upstream, so it cannot be refused when the form is saved, only
    pointed at once it is true.

    Args:
        views: Every interface with its live state.

    Returns:
        One sentence per problem found, in the order they were found.
    """
    active = [
        (view, subnet)
        for view in views
        # A split port's address belongs to its untagged main, which is its
        # own view; counting the port too would report the pair as a clash.
        if view.settings.role not in ("disabled", ROUTER_ROLE_SPLIT)
        and view.link.ipv4_address
        for subnet in [_subnet(view.link.ipv4_address)]
        if subnet is not None
    ]
    warnings = []
    for index, (view, subnet) in enumerate(active):
        for other, other_subnet in active[index + 1 :]:
            if not subnet.overlaps(other_subnet):
                continue
            roles = {view.settings.role, other.settings.role}
            if roles == {ROUTER_ROLE_WAN}:
                # Two uplinks onto one segment is one line reached twice. That
                # is now handled rather than merely reported: the planner puts
                # the second on standby and the diagram draws them converging,
                # so there is nothing left to warn about.
                continue
            warnings.append(
                f"{view.settings.name} and {other.settings.name} both hold an "
                f"address on {subnet}, one serving it and one reaching the "
                f"internet through it. The gateway cannot both be a client of "
                f"a network and hand out addresses on it; move one of them."
            )
    return warnings


def _tab_order(
    interface: RouterInterface, physical_order: dict[str, int]
) -> tuple[int, int, int]:
    unknown = len(physical_order)
    if interface.vlan is None:
        return (physical_order.get(interface.name, unknown), 0, -1)
    return (
        physical_order.get(interface.vlan.parent, unknown),
        1,
        -1 if interface.vlan.id is None else interface.vlan.id,
    )


def _subnet(address: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        return ipaddress.ip_network(address, strict=False)
    except ValueError:
        return None


async def _apply(runtime: PanelRuntime, *, only: str | None) -> None:
    try:
        await runtime.apply_network(only=only)
    except CommandError as error:
        raise _bad_gateway(str(error)) from error


def _to_settings(interface: RouterInterface) -> InterfaceSettings:
    return InterfaceSettings.model_validate(interface.to_dict())


def _propose_lan(
    settings: InterfaceSettings, *, network: RouterNetworkConfig
) -> InterfaceSettings:
    """Fill in a usable network for an interface that has never served one.

    Choosing a subnet is the one part of switching an interface to the LAN role
    that has a right answer nobody wants to work out: any private range that
    does not collide with the ones already in use. So the page arrives with one
    filled in. Nothing is stored until the form is saved, and typing over it
    costs a keystroke.

    Args:
        settings: The interface's settings as stored.
        network: The whole configuration, for the subnets already taken.

    Returns:
        The settings, with a LAN address filled in when there was none.
    """
    if settings.lan.address:
        return settings
    taken = {
        other.lan.address
        for other in network.interfaces
        if other.name != settings.name and other.lan.address
    }
    for octet in range(100, 200):
        address = f"192.168.{octet}.1"
        if address in taken:
            continue
        settings.lan.address = address
        settings.lan.prefix_len = 24
        settings.lan.dhcp_range_start = f"192.168.{octet}.100"
        settings.lan.dhcp_range_end = f"192.168.{octet}.200"
        break
    return settings


def _to_interface(settings: InterfaceSettings) -> RouterInterface:
    return RouterInterface.from_dict(settings.model_dump())


def _require_wifi(name: str) -> None:
    link = RouterLinkStatus().link(name)
    if link.kind != LINK_KIND_WIFI:
        raise _bad_request(f"{name} is not a wireless interface")


def _validate(
    settings: InterfaceSettings, *, link: LinkStatus, network: RouterNetworkConfig
) -> None:
    if settings.role not in ROUTER_ROLES:
        raise _bad_request(f"unknown role {settings.role!r}")
    stored = network.interface(settings.name)
    if stored is not None and stored.is_vlan != (settings.vlan is not None):
        raise _bad_request(
            f"{settings.name} cannot change between a physical port and a VLAN"
        )
    if settings.vlan is not None:
        _validate_vlan(settings, network=network)
    elif settings.role == ROUTER_ROLE_SPLIT:
        if link.kind != LINK_KIND_ETHERNET:
            raise _bad_request("only a wired port can be split into VLANs")
    if settings.role == ROUTER_ROLE_LAN:
        _validate_lan(settings, link=link, network=network)
    elif settings.role == ROUTER_ROLE_WAN:
        _validate_wan(settings)


def _validate_vlan(
    settings: InterfaceSettings, *, network: RouterNetworkConfig
) -> None:
    vlan = settings.vlan
    if settings.role == ROUTER_ROLE_SPLIT:
        raise _bad_request("a VLAN cannot itself be split")
    if vlan.id is None:
        if settings.name != f"{vlan.parent}.main":
            raise _bad_request(
                f"the untagged main is named after its trunk: {vlan.parent}.main"
            )
    else:
        if not ROUTER_VLAN_ID_MIN <= vlan.id <= ROUTER_VLAN_ID_MAX:
            raise _bad_request(
                f"the VLAN id must be between {ROUTER_VLAN_ID_MIN} "
                f"and {ROUTER_VLAN_ID_MAX}"
            )
        if settings.name != f"{vlan.parent}.{vlan.id}":
            raise _bad_request(
                f"a VLAN interface is named after its trunk and id: "
                f"{vlan.parent}.{vlan.id}"
            )
    parent = network.interface(vlan.parent)
    if parent is None or not parent.is_split:
        raise _bad_request(f"{vlan.parent} is not split, so it can carry no VLANs")


def _validate_lan(
    settings: InterfaceSettings, *, link: LinkStatus, network: RouterNetworkConfig
) -> None:
    lan = settings.lan
    try:
        subnet = ipaddress.ip_network(f"{lan.address}/{lan.prefix_len}", strict=False)
        address = ipaddress.ip_address(lan.address)
    except ValueError as error:
        raise _bad_request(str(error)) from error

    # Two LANs on overlapping subnets would give clients on either one an
    # ambiguous route, and dnsmasq would hand out leases from whichever pool it
    # matched first.
    for other in network.lan_interfaces:
        if other.name == settings.name or not other.lan.address:
            continue
        try:
            other_subnet = ipaddress.ip_network(other.lan.cidr, strict=False)
        except ValueError:
            continue
        if subnet.overlaps(other_subnet):
            raise _bad_request(
                f"{subnet} overlaps the network {other.name} already serves "
                f"({other_subnet})"
            )

    if lan.upstream_gateway:
        try:
            upstream = ipaddress.ip_address(lan.upstream_gateway)
        except ValueError as error:
            raise _bad_request(f"upstream router: {error}") from error
        if upstream not in subnet:
            raise _bad_request(f"the upstream router must lie inside {subnet}")
        if upstream == address:
            raise _bad_request(
                "the upstream router cannot be the gateway's own address"
            )

    if lan.is_dhcp_enabled:
        try:
            start = ipaddress.ip_address(lan.dhcp_range_start)
            end = ipaddress.ip_address(lan.dhcp_range_end)
        except ValueError as error:
            raise _bad_request(str(error)) from error
        if start not in subnet or end not in subnet:
            raise _bad_request(f"the DHCP range must lie inside {subnet}")
        if start > end:
            raise _bad_request("the DHCP range start must not be above its end")
        if start <= address <= end:
            raise _bad_request("the gateway address must lie outside the DHCP range")

    if link.kind == LINK_KIND_WIFI:
        if lan.upstream_gateway:
            raise _bad_request(
                "a published access point cannot be a side gateway; joining "
                "an existing network over the radio is the WAN role"
            )
        if not link.is_ap_capable:
            raise _bad_request(
                f"{settings.name} cannot serve a network: its chipset has no "
                f"access-point mode, so it can only join one"
            )
        if not settings.wifi.ap_ssid.strip():
            raise _bad_request("an access point needs a network name")
        length = len(settings.wifi.ap_passphrase)
        if not AP_PASSPHRASE_MIN_LENGTH <= length <= AP_PASSPHRASE_MAX_LENGTH:
            raise _bad_request(
                f"the access point passphrase must be "
                f"{AP_PASSPHRASE_MIN_LENGTH} to {AP_PASSPHRASE_MAX_LENGTH} characters"
            )


def _validate_wan(settings: InterfaceSettings) -> None:
    wan = settings.wan
    if wan.intent not in ROUTER_INTENTS:
        raise _bad_request(f"unknown uplink intent {wan.intent!r}")
    if wan.method != ROUTER_WAN_METHOD_STATIC:
        return
    try:
        subnet = ipaddress.ip_network(f"{wan.address}/{wan.prefix_len}", strict=False)
    except ValueError as error:
        raise _bad_request(f"static uplink address: {error}") from error
    if not wan.gateway:
        raise _bad_request("a static uplink needs a gateway address")
    try:
        gateway = ipaddress.ip_address(wan.gateway)
    except ValueError as error:
        raise _bad_request(f"static uplink gateway: {error}") from error
    if gateway not in subnet:
        raise _bad_request(f"the gateway must lie inside {subnet}")


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _bad_gateway(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
