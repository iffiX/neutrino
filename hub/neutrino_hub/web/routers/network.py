"""The Network tab: what each interface is for, and what it is doing.

Every interface carries a role — uplink, served network, or unused — and saving
one applies it on its own. That is deliberate: an interface is the unit a person
thinks about here, and applying the whole page at once would mean a typo in the
Wi-Fi settings could take the wired LAN down with it.
"""

import asyncio
from contextlib import suppress
import ipaddress
import re
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.router.constants import (
    ROUTER_INTENTS,
    ROUTER_LEASE_TIME_PATTERN,
    ROUTER_MAC_PATTERN,
    ROUTER_PREFIX_LEN_MAX,
    ROUTER_PREFIX_LEN_MIN,
    ROUTER_MODE_ROUTER,
    ROUTER_MODE_SIDE_GATEWAY,
    ROUTER_MODES_KEYS,
    ROUTER_KEY_MGMT_NONE,
    ROUTER_KEY_MGMT_PSK,
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
from neutrino_hub.modules.router.connections import RouterConnection
from neutrino_hub.modules.router.credentials import RouterCredentialReader
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_KIND_WIFI,
    LinkStatus,
    RouterLinkStatus,
    device_addresses,
)
from neutrino_hub.modules.router.modes import (
    ROUTER_MODE_DEFAULT_PREFIX_LEN,
    ROUTER_MODES_BY_KEY,
)
from neutrino_hub.modules.router.routes import (
    build_uplink_plan,
    hand_back,
    remove_vlan_device,
)
from neutrino_hub.modules.router.supplicant import RouterWifiClient, write_config
from neutrino_hub.modules.router.wifi import (
    AP_PASSPHRASE_MAX_LENGTH,
    AP_PASSPHRASE_MIN_LENGTH,
)
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    SavedNetworkListView,
    SavedNetworkView,
    InterfaceLink,
    InterfaceSettings,
    InterfaceView,
    NetworkModeRequest,
    NetworkModeView,
    NetworkOptions,
    NetworkView,
    OverlayView,
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


@router.put("", response_model=NetworkView)
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
        HTTPException: 400 for an unknown policy or an interface this machine
            does not have, 502 when the firewall reload fails.
    """
    if options.uplink_policy not in ROUTER_POLICIES:
        raise _bad_request("uplink_policy_unknown", policy=options.uplink_policy)
    network = runtime.network()
    network.uplink_policy = options.uplink_policy
    network.is_inter_lan_allowed = options.is_inter_lan_allowed
    _set_exposure(network, options.exposed_interfaces, runtime=runtime)
    if options.exposed_overlays is not None:
        wanted = set(options.exposed_overlays)
        for overlay in network.overlays:
            overlay.is_exposed = overlay.provider in wanted
    runtime.write_network(network)
    await _apply(runtime, only=None)
    return _build_view(runtime)


@router.put("/mode", response_model=NetworkView)
async def update_mode(
    request: NetworkModeRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NetworkView:
    """Make this machine a different shape.

    Its own resource rather than one of the settings above, because writing it
    is not writing a value: it decides whether the hub addresses this machine
    at all, so leaving the router mode hands the network back to whatever ran
    it before and entering it starts from the addresses the ports have now.

    What each role is stays with the interfaces. The mode only takes away the
    roles the new shape cannot have — a server routes nothing — and names the
    one a side gateway is built on, which is the port already carrying the way
    out. Everything else is configured where it always was.

    Args:
        request: The mode to become.
        runtime: The shared runtime.

    Returns:
        The Network tab payload.

    Raises:
        HTTPException: 400 for a mode that is not one of them, 502 when
            applying the new shape fails.
    """
    if request.mode not in ROUTER_MODES_KEYS:
        raise _bad_request("network_mode_unknown", mode=request.mode)
    network = runtime.network()
    if request.mode == network.mode:
        return _build_view(runtime)

    is_leaving = network.is_addressing_owned
    network.mode = request.mode
    orphaned = _retune_roles(network, runtime=runtime)
    if is_leaving and not network.is_addressing_owned:
        # Before the new shape is applied, and read from the interfaces it is
        # about to stop driving.
        await asyncio.to_thread(hand_back, network)
    if network.is_addressing_owned and not is_leaving:
        _adopt_known_networks(runtime)
    _adopt_live_addressing(network)
    runtime.write_network(network)
    for name in orphaned:
        await asyncio.to_thread(remove_vlan_device, name)
    await _apply(runtime, only=None)
    return _build_view(runtime)


def _retune_roles(network: RouterNetworkConfig, *, runtime: PanelRuntime) -> list[str]:
    """Take away the roles the new mode cannot have, and give the one it needs.

    A server routes nothing, so no port holds a role in it. A side gateway
    holds exactly one: the port already carrying the way out, which is the
    network it forwards for. A router keeps every role it had — what each
    interface is for is the interface panel's question, not the mode's — and
    loses only the upstream router a side gateway had left on one of them.

    Args:
        network: The configuration, already carrying its new mode.
        runtime: The shared runtime, for which port carries the way out.

    Returns:
        The VLAN interfaces the new mode has no place for, whose devices are
        the caller's to remove.
    """
    if network.mode == ROUTER_MODE_ROUTER:
        # A router's way out is an uplink. A served network whose own router is
        # the way out is the side gateway this machine has stopped being, and
        # the panel has no field for it here.
        for interface in network.interfaces:
            interface.lan.upstream_gateway = None
        return []
    # A VLAN is a device the hub built on a trunk. Neither mode has trunks, so
    # the entries go rather than being kept as entries that claim to be ports:
    # one of those can never be deleted, and the tag can never be made again.
    removed = [interface.name for interface in network.interfaces if interface.is_vlan]
    for name in removed:
        network.remove(name)
    for interface in network.interfaces:
        interface.role = ROUTER_ROLE_DISABLED
    if network.mode != ROUTER_MODE_SIDE_GATEWAY:
        return removed
    status = runtime.link_status()
    joined = next(
        (
            link.name
            for link in status.all_links()
            if status.gateway_for(link.name) is not None
        ),
        None,
    )
    if joined is None:
        return removed
    interface = network.interface_or_new(joined)
    interface.role = ROUTER_ROLE_LAN
    interface.lan.is_dhcp_enabled = False
    interface.lan.upstream_gateway = status.gateway_for(joined)
    # A served network answers by definition: it is where the panel, the
    # leases and DNS are reached, and the planner sets this for the same
    # reason when the wizard builds one.
    interface.is_exposed = True
    network.replace(interface)
    return removed


def _set_exposure(
    network: RouterNetworkConfig, names: list[str], *, runtime: PanelRuntime
) -> None:
    """Write which interfaces answer, creating entries for ports that had none.

    Args:
        network: The configuration to change.
        names: The interfaces that answer. Everything else stops answering.
        runtime: The shared runtime, for the ports this machine has.

    Raises:
        HTTPException: 400 when a named interface is neither configured nor
            present on this machine.
    """
    present = {link.name for link in runtime.link_status().all_links()}
    wanted = set(names)
    for name in wanted:
        if name not in present and network.interface(name) is None:
            raise _bad_request("interface_not_on_machine", name=name)
        opened = network.interface_or_new(name)
        opened.is_exposed = True
        network.replace(opened)
    for interface in network.interfaces:
        if interface.name not in wanted:
            interface.is_exposed = False


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
        raise _bad_request("interface_name_mismatch")

    network = runtime.network()
    saved = _to_interface(settings, network=network)
    status_reader = RouterLinkStatus()
    link = status_reader.link(saved.device_name)
    _require_present(settings, network=network, status=status_reader)
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
                is_exposed=saved.is_exposed,
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
            detail={"code": "interface_not_configured", "params": {"name": name}},
        )
    if interface.vlan is None:
        raise _bad_request("interface_not_a_vlan", name=name)
    if interface.is_untagged:
        raise _bad_request("untagged_main_not_removable")

    parent = interface.vlan.parent
    network.remove(name)
    runtime.write_network(network)
    await asyncio.to_thread(remove_vlan_device, name)
    only = parent if network.interface(parent) is not None else None
    await _apply(runtime, only=only)
    return _build_view(runtime)


@router.get("/wifi_networks", response_model=SavedNetworkListView)
def list_saved_networks(
    runtime: PanelRuntime = Depends(get_runtime),
) -> SavedNetworkListView:
    """Read every wireless network the box knows how to join.

    Args:
        runtime: The shared runtime.

    Returns:
        The networks, the ones it would prefer first. No passphrase comes back
        out — only whether one is held.
    """
    known = runtime.connections()
    return SavedNetworkListView(
        networks=[
            _to_saved_view(connection)
            for connection in sorted(
                known.connections, key=lambda item: (-item.priority, item.ssid)
            )
        ]
    )


@router.delete("/wifi_networks/{ssid}", response_model=SavedNetworkListView)
async def forget_network(
    ssid: str, runtime: PanelRuntime = Depends(get_runtime)
) -> SavedNetworkListView:
    """Forget a wireless network, so no radio joins it again.

    The radio holding it now is not disconnected: dropping a link somebody may
    be reading the panel over, to act on a list they were tidying, is not what
    the button says. It goes when the radio next has cause to reassociate.

    Args:
        ssid: The network name.
        runtime: The shared runtime.

    Returns:
        What the box knows now.

    Raises:
        HTTPException: 404 when the box does not know that network.
    """
    known = runtime.connections()
    if not known.remove(ssid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "wifi_network_unknown", "params": {"ssid": ssid}},
        )
    runtime.write_connections(known)
    await asyncio.to_thread(_rerender_radios, runtime, known)
    return await asyncio.to_thread(list_saved_networks, runtime)


def _rerender_radios(runtime: PanelRuntime, known) -> None:
    """Write every radio's configuration again and have it re-read.

    Args:
        runtime: The shared runtime.
        known: The networks the box knows now.
    """
    status_reader = RouterLinkStatus()
    for link in status_reader.all_links():
        if link.kind != LINK_KIND_WIFI:
            continue
        write_config(link.name, known)
        client = RouterWifiClient(interface=link.name)
        if client.is_running:
            with suppress(subprocess.SubprocessError, OSError):
                client.reconfigure()


def _to_saved_view(connection) -> SavedNetworkView:
    return SavedNetworkView(
        ssid=connection.ssid,
        key_mgmt=connection.key_mgmt,
        has_secret=connection.has_secret,
        priority=connection.priority,
        is_hidden=connection.is_hidden,
        source=connection.source,
    )


@router.get("/interfaces/{name}/wifi/scan", response_model=WifiScanView)
def scan_wifi(name: str, runtime: PanelRuntime = Depends(get_runtime)) -> WifiScanView:
    """Scan for the networks a wireless interface can see.

    Args:
        name: Interface name.
        runtime: The shared runtime, for which networks the box already knows.

    Returns:
        What the scan found, strongest first.

    Raises:
        HTTPException: 400 when the interface is not wireless, 502 when the
            scan fails.
    """
    _require_wifi(name)
    client = RouterWifiClient(interface=name)
    try:
        found = client.scan()
    except (subprocess.SubprocessError, OSError) as error:
        raise _bad_gateway(
            "command_failed", detail=command_failure_text(error)
        ) from error
    # Which networks are already known is the hub's own answer now, out of
    # `config/`, rather than a question put to whatever manager held them.
    known = runtime.connections()
    joined = client.joined_ssid()
    return WifiScanView(
        networks=[
            WifiNetworkView(
                ssid=network["ssid"],
                signal_percent=network["signal_percent"],
                security=network["security"],
                is_active=network["ssid"] == joined,
                is_saved=known.find(network["ssid"]) is not None,
            )
            for network in found
            # An enterprise network needs a certificate and an identity, which
            # is not something this asks for. Offering it would take a
            # passphrase and fail.
            if not network["is_enterprise"]
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
        await asyncio.to_thread(_join, runtime, name, request)
    except (subprocess.SubprocessError, OSError) as error:
        raise _bad_gateway(
            "wifi_join_failed",
            ssid=request.ssid,
            detail=command_failure_text(error),
        ) from error

    network = runtime.network()
    interface = network.interface_or_new(name)
    interface.role = ROUTER_ROLE_WAN
    interface.wifi.ssid = request.ssid
    network.replace(interface)
    runtime.write_network(network)
    await _apply(runtime, only=name)
    return _build_view(runtime)


def _adopt_live_addressing(network: RouterNetworkConfig) -> None:
    """Write down what the machine already has, before the hub starts setting it.

    Taking a machine over has to reproduce the addressing it arrived with,
    not blank it. An interface that was only ever answered on has an empty
    address in `config/` — nobody typed one, because nobody had to — and
    applying that would take the address away rather than keep it.

    Only what is empty is filled in. An address somebody typed is a decision,
    and a decision is not overwritten by what happens to be live.

    Args:
        network: The configuration about to become the hub's to apply.
    """
    status = RouterLinkStatus()
    for interface in network.interfaces:
        link = status.link(interface.device_name)
        if link.ipv4_address is None:
            continue
        address, _, prefix_len = link.ipv4_address.partition("/")
        if interface.is_lan and not interface.lan.address:
            interface.lan.address = address
            interface.lan.prefix_len = int(prefix_len or ROUTER_MODE_DEFAULT_PREFIX_LEN)


def _join(runtime: PanelRuntime, name: str, request: WifiJoinRequest) -> None:
    """Have a radio associate with one network.

    Not a command to the radio: the network is written into `config/`, the
    radio's configuration is rendered from it, and the supplicant is told to
    read the file again. That is what makes the association survive a reboot
    without anything having to remember to redo it.

    Args:
        runtime: The shared runtime.
        name: The radio.
        request: The network to join and, when it is not already known, its
            passphrase.

    Raises:
        subprocess.CalledProcessError: When a step of the association fails.
        TimeoutError: When the radio does not join in time. The message says
            what the supplicant was doing, because a wrong passphrase and a
            network out of range look different there.
    """
    known = runtime.connections()
    existing = known.find(request.ssid)
    if request.passphrase:
        known.replace(
            RouterConnection(
                ssid=request.ssid,
                key_mgmt=ROUTER_KEY_MGMT_PSK,
                psk=request.passphrase,
            )
        )
    elif existing is None or not existing.has_secret:
        # Nothing was typed and nothing is held. An open network is the one
        # case where that is fine.
        known.replace(
            RouterConnection(ssid=request.ssid, key_mgmt=ROUTER_KEY_MGMT_NONE)
        )
    runtime.write_connections(known)

    write_config(name, known)
    client = RouterWifiClient(interface=name)
    if client.is_running:
        client.reconfigure()
    else:
        client.start()
    client.wait_for_association()


def _adopt_known_networks(runtime: PanelRuntime) -> None:
    """Read the wireless networks whatever ran this machine already held.

    Taking a radio over means the hub has to know the passphrase of the
    network it was on, and on a machine that has been somebody's laptop that
    passphrase is already on the disk. Reading it is the difference between a
    box that keeps working and one that asks for every network again.

    What is read is a subset, never a guess: a store that cannot be parsed is
    skipped, and a network already held here is left alone — somebody typed
    that one, and a decision is not overwritten by what was found lying about.

    Args:
        runtime: The shared runtime.
    """
    known = runtime.connections()
    is_changed = False
    for found in RouterCredentialReader().read_all():
        if known.find(found.ssid) is None:
            known.replace(found)
            is_changed = True
    if is_changed:
        runtime.write_connections(known)


def _reaching_addresses(runtime: PanelRuntime) -> list[str]:
    """Where the managed devices currently on the channel are reaching from.

    Live rather than remembered: what closing a network costs is the links it
    would end, and a device that is off right now has no link to end. Saying
    "3 devices" of machines nobody can see would be a number the person
    cannot check.

    Args:
        runtime: The shared runtime, which holds each connected device's peer
            address.

    Returns:
        One address per connected device.
    """
    return [address for address in runtime.client_address.values() if address]


def _count_reaching(addresses: list[str], cidr: str) -> int:
    """How many of those addresses are on one network.

    Args:
        addresses: The connected devices' addresses.
        cidr: The network, as ``a.b.c.d/nn``.

    Returns:
        The count, zero for a network that cannot be parsed.
    """
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return 0
    counted = 0
    for address in addresses:
        try:
            if ipaddress.ip_address(address) in network:
                counted += 1
        except ValueError:
            continue
    return counted


def _overlay_views(
    network: RouterNetworkConfig, *, runtime: PanelRuntime
) -> list[OverlayView]:
    """The overlay rows for the Exposure panel.

    Args:
        network: The parsed configuration.
        runtime: The shared runtime, for the devices on the channel.

    Returns:
        One row per configured overlay, in configuration order.
    """
    addresses = device_addresses()
    reaching = _reaching_addresses(runtime)
    views = []
    for overlay in network.overlays:
        cidr = addresses.get(overlay.device_name, "")
        views.append(
            OverlayView(
                provider=overlay.provider,
                title=overlay.title,
                address=cidr.split("/")[0] if cidr else "",
                is_exposed=overlay.is_exposed,
                device_count=_count_reaching(reaching, cidr) if cidr else 0,
            )
        )
    return views


def _build_view(runtime: PanelRuntime) -> NetworkView:
    network = runtime.network()
    status_reader = runtime.link_status()
    links = {link.name: link for link in status_reader.all_links()}
    reaching = _reaching_addresses(runtime)

    names = list(links)
    for interface in network.interfaces:
        if interface.name not in links:
            names.append(interface.name)
    # Tabs read left to right as the box is wired: each port, then what rides
    # on it — the untagged main first, then its VLANs by tag.
    physical_order = {name: index for index, name in enumerate(names)}
    names.sort(
        key=lambda name: _tab_order(network.interface_or_new(name), physical_order)
    )

    views = []
    for name in names:
        interface = network.interface_or_new(name)
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
                    ssid=link.ssid,
                    signal_percent=link.signal_percent,
                    speed_mbps=link.speed_mbps,
                    gateway=status_reader.gateway_for(interface.device_name),
                    is_ap_capable=link.is_ap_capable,
                    device_count=_count_reaching(reaching, link.ipv4_address or ""),
                ),
            )
        )
    plan = build_uplink_plan(network=network, status=status_reader)
    return NetworkView(
        mode=network.mode,
        modes=_mode_views(),
        interfaces=views,
        overlays=_overlay_views(network, runtime=runtime),
        uplink_policy=network.uplink_policy,
        is_inter_lan_allowed=network.is_inter_lan_allowed,
        is_addressing_owned=network.is_addressing_owned,
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


def _mode_views() -> list[NetworkModeView]:
    """The modes the panel offers, in the order it draws them.

    Every one of them, whatever ports the machine has: switching asks for no
    port, so there is nothing a machine could be too small for. A router on
    one wire is a router whose port is a trunk, which is the interface panel's
    business.

    Returns:
        One entry per mode.
    """
    return [
        NetworkModeView(
            key=mode.key,
            is_addressing_owned=mode.is_addressing_owned,
        )
        for mode in (ROUTER_MODES_BY_KEY[key] for key in ROUTER_MODES_KEYS)
    ]


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
    except (
        subprocess.SubprocessError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise _bad_gateway(
            "command_failed", detail=command_failure_text(error)
        ) from error


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


def _to_interface(
    settings: InterfaceSettings, *, network: RouterNetworkConfig
) -> RouterInterface:
    # Whether an interface answers is written by the panel that shows all of
    # them at once. Taking it from what is stored, not from the body, is what
    # keeps saving one interface's role from quietly reopening or closing it.
    interface = RouterInterface.from_dict(settings.model_dump())
    stored = network.interface(settings.name)
    interface.is_exposed = stored.is_exposed if stored else False
    return interface


def _require_wifi(name: str) -> None:
    link = RouterLinkStatus().link(name)
    if link.kind != LINK_KIND_WIFI:
        raise _bad_request("interface_not_wireless", name=name)


def _require_present(
    settings: InterfaceSettings,
    *,
    network: RouterNetworkConfig,
    status: RouterLinkStatus,
) -> None:
    """Refuse an interface this machine does not have and is not about to.

    The link reader answers for a name it has never heard of with a blank
    entry rather than nothing, so validation passes for anything at all. What
    is written then draws as a tab, has no VLAN block so it can never be
    deleted, and makes every apply — the panel's and the one at boot — fail on
    a device that is not there.

    Args:
        settings: What was submitted.
        network: The stored configuration.
        status: The live link reader.

    Raises:
        HTTPException: 400 when the name is neither a device on this machine
            nor a VLAN the hub is being asked to build.
    """
    if settings.vlan is not None or network.interface(settings.name) is not None:
        return
    if any(link.name == settings.name for link in status.all_links()):
        return
    raise _bad_request("interface_not_on_machine", name=settings.name)


def _validate(
    settings: InterfaceSettings, *, link: LinkStatus, network: RouterNetworkConfig
) -> None:
    if settings.role not in ROUTER_ROLES:
        raise _bad_request("interface_role_unknown", role=settings.role)
    stored = network.interface(settings.name)
    if stored is not None and stored.is_vlan != (settings.vlan is not None):
        raise _bad_request("interface_kind_fixed", name=settings.name)
    if settings.vlan is not None:
        _validate_vlan(settings, network=network)
    elif settings.role == ROUTER_ROLE_SPLIT:
        if link.kind != LINK_KIND_ETHERNET:
            raise _bad_request("split_needs_wired_port")
    # Both blocks are checked whatever the role is live. Every interface keeps
    # all of them so that switching a port back and forth loses nothing, and
    # splitting one copies them verbatim onto the untagged main — so a value
    # stored under a role nobody is using becomes the value that is applied
    # the moment somebody selects it.
    if settings.wan.cloned_mac and not re.match(
        ROUTER_MAC_PATTERN, settings.wan.cloned_mac
    ):
        raise _bad_request("cloned_mac_invalid", value=settings.wan.cloned_mac)
    if settings.role == ROUTER_ROLE_LAN:
        _validate_lan(settings, link=link, network=network)
    elif settings.role == ROUTER_ROLE_WAN:
        _validate_wan(settings)


def _validate_vlan(
    settings: InterfaceSettings, *, network: RouterNetworkConfig
) -> None:
    vlan = settings.vlan
    if settings.role == ROUTER_ROLE_SPLIT:
        raise _bad_request("vlan_cannot_be_split")
    if vlan.id is None:
        if settings.name != f"{vlan.parent}.main":
            raise _bad_request("untagged_main_name_fixed", name=f"{vlan.parent}.main")
    else:
        if not ROUTER_VLAN_ID_MIN <= vlan.id <= ROUTER_VLAN_ID_MAX:
            raise _bad_request(
                "vlan_id_out_of_range",
                minimum=ROUTER_VLAN_ID_MIN,
                maximum=ROUTER_VLAN_ID_MAX,
            )
        if settings.name != f"{vlan.parent}.{vlan.id}":
            raise _bad_request("vlan_name_fixed", name=f"{vlan.parent}.{vlan.id}")
    parent = network.interface(vlan.parent)
    if parent is None or not parent.is_split:
        raise _bad_request("vlan_parent_not_split", parent=vlan.parent)


def _validate_lan(
    settings: InterfaceSettings, *, link: LinkStatus, network: RouterNetworkConfig
) -> None:
    lan = settings.lan
    _require_prefix_len(lan.prefix_len)
    if lan.is_dhcp_enabled and not re.match(
        ROUTER_LEASE_TIME_PATTERN, lan.dhcp_lease_time.strip()
    ):
        raise _bad_request("dhcp_lease_time_invalid", value=lan.dhcp_lease_time)
    try:
        subnet = ipaddress.ip_network(f"{lan.address}/{lan.prefix_len}", strict=False)
        address = ipaddress.ip_address(lan.address)
    except ValueError as error:
        raise _bad_request("lan_address_invalid", address=lan.address) from error

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
                "lan_subnet_overlaps",
                subnet=str(subnet),
                name=other.name,
                other=str(other_subnet),
            )

    if lan.upstream_gateway:
        try:
            upstream = ipaddress.ip_address(lan.upstream_gateway)
        except ValueError as error:
            raise _bad_request(
                "upstream_gateway_invalid", address=lan.upstream_gateway
            ) from error
        if upstream not in subnet:
            raise _bad_request("upstream_gateway_outside", subnet=str(subnet))
        if upstream == address:
            raise _bad_request("upstream_gateway_is_this_box")

    if lan.is_dhcp_enabled:
        try:
            start = ipaddress.ip_address(lan.dhcp_range_start)
            end = ipaddress.ip_address(lan.dhcp_range_end)
        except ValueError as error:
            raise _bad_request(
                "dhcp_range_invalid",
                start=lan.dhcp_range_start,
                end=lan.dhcp_range_end,
            ) from error
        if start not in subnet or end not in subnet:
            raise _bad_request("dhcp_range_outside", subnet=str(subnet))
        if start > end:
            raise _bad_request("dhcp_range_reversed")
        if start <= address <= end:
            raise _bad_request("dhcp_range_holds_gateway")

    if link.kind == LINK_KIND_WIFI:
        if lan.upstream_gateway:
            raise _bad_request("access_point_cannot_be_side_gateway")
        if not link.is_ap_capable:
            raise _bad_request("interface_not_ap_capable", name=settings.name)
        if not settings.wifi.ap_ssid.strip():
            raise _bad_request("access_point_needs_ssid")
        length = len(settings.wifi.ap_passphrase)
        if not AP_PASSPHRASE_MIN_LENGTH <= length <= AP_PASSPHRASE_MAX_LENGTH:
            raise _bad_request(
                "access_point_passphrase_length",
                minimum=AP_PASSPHRASE_MIN_LENGTH,
                maximum=AP_PASSPHRASE_MAX_LENGTH,
            )


def _validate_wan(settings: InterfaceSettings) -> None:
    wan = settings.wan
    if wan.intent not in ROUTER_INTENTS:
        raise _bad_request("uplink_intent_unknown", intent=wan.intent)
    if wan.method != ROUTER_WAN_METHOD_STATIC:
        return
    _require_prefix_len(wan.prefix_len)
    try:
        subnet = ipaddress.ip_network(f"{wan.address}/{wan.prefix_len}", strict=False)
    except ValueError as error:
        raise _bad_request("uplink_address_invalid", address=wan.address) from error
    if not wan.gateway:
        raise _bad_request("uplink_gateway_needed")
    try:
        gateway = ipaddress.ip_address(wan.gateway)
    except ValueError as error:
        raise _bad_request("uplink_gateway_invalid", address=wan.gateway) from error
    if gateway not in subnet:
        raise _bad_request("uplink_gateway_outside", subnet=str(subnet))


def _require_prefix_len(prefix_len: int) -> None:
    """Refuse a mask that is not one.

    A `/0` is accepted by `ip_network` and is not a network: it makes every
    containment check after it pass, so a lease range on another continent and
    an upstream router that is not on the wire both read as valid.

    Args:
        prefix_len: What was submitted.

    Raises:
        HTTPException: 400 when it is outside the usable range.
    """
    if not ROUTER_PREFIX_LEN_MIN <= prefix_len <= ROUTER_PREFIX_LEN_MAX:
        raise _bad_request(
            "prefix_len_out_of_range",
            minimum=ROUTER_PREFIX_LEN_MIN,
            maximum=ROUTER_PREFIX_LEN_MAX,
            value=prefix_len,
        )


def _bad_request(code: str, **params) -> HTTPException:
    """One 400 carrying the name of what happened.

    Args:
        code: What was refused.
        params: The values the panel's sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )


def _bad_gateway(code: str, **params) -> HTTPException:
    """One 502 carrying the name of what happened.

    Args:
        code: What was refused.
        params: The values the panel's sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": code, "params": params},
    )
