"""What the hub keeps of an agent's hello and its reports.

An agent's socket opens with one ``hello`` and then carries a ``report``
every few seconds. Both land in the runtime's memory alone, which is what
the panel reads: a machine's presence is true only while this hub runs.

A report is read by its sections: ``machine``, ``network``, ``modules``,
``desktop`` and ``error``. It writes three things. The seat password: a
machine reporting the remote desktop host present is given one, sealed
under the vault's data key, the first time it says so. The MAC its socket
runs on, noted on the device's row when it is new. And ``modules.json``: a
module the hub wanted ``absent`` that the machine now reports absent is
dropped from it, so the hub's state stops naming software it took off.
"""

import ipaddress

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_PRESENT_STATES,
    CHANNEL_MODULE_STATE_ABSENT,
)
from neutrino_hub.modules.devices.constants import DEVICE_RDP_MODULE
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.constants import SERVICES_RDP_PORT


def record_hello(
    runtime, device, *, name: str, peer_host: str, reached_host: str
) -> None:
    """Take what a machine says it is when its socket opens.

    Args:
        runtime: The shared runtime.
        device: The device the token resolved to.
        name: What the hello called the machine.
        peer_host: Where the socket comes from; the device's address until
            a report names one.
        reached_host: The address the machine connected to.
    """
    key = device.id
    if name:
        runtime.device_hostname[key] = name
    if peer_host:
        runtime.device_address[key] = peer_host
    runtime.device_hub_host[key] = device_host(
        runtime, runtime.device_address.get(key, ""), reached_host
    )


def record_report(runtime, device, report: dict, *, peer_host: str = "") -> None:
    """Take one report: what is true of the machine right now.

    Args:
        runtime: The shared runtime.
        device: The device the socket belongs to.
        report: The report message.
        peer_host: Where the socket comes from, the address recorded when
            the report's link names none.
    """
    key = device.id
    _record_machine(runtime, key, report.get("machine"))
    _record_network(runtime, device, report.get("network"), peer_host=peer_host)
    modules = report.get("modules")
    modules = dict(modules) if isinstance(modules, dict) else {}
    runtime.device_modules[key] = modules
    is_settled = _settle_absent(runtime, key, modules)
    is_seated = _ensure_seat_password(runtime, key, modules)
    if is_settled or is_seated:
        _push_state(runtime, key)
    record_desktop_share(
        runtime,
        device,
        report.get("desktop") or {},
        runtime.device_address.get(key, ""),
    )
    error = report.get("error")
    if isinstance(error, dict) and error.get("code"):
        runtime.device_last_error[key] = {
            "code": str(error.get("code")),
            "params": dict(error.get("params") or {}),
        }
    else:
        runtime.device_last_error.pop(key, None)


def record_offline(runtime, device) -> None:
    """Take a socket ending: whatever the machine hosted stops with it.

    Args:
        runtime: The shared runtime.
        device: The device whose socket ended.
    """
    record_desktop_share(runtime, device, {}, runtime.device_address.get(device.id, ""))


def link_address(network: dict, peer_host: str) -> str:
    """Where a machine is: the address its socket leaves by, else the peer's.

    Args:
        network: The message's ``network`` section.
        peer_host: Where the socket comes from, the fallback.

    Returns:
        ``network.link.address`` when the message names one, else
        ``peer_host``.
    """
    link = network.get("link") if isinstance(network, dict) else None
    address = str(link.get("address", "") or "") if isinstance(link, dict) else ""
    return address or peer_host


def device_host(runtime, device_ip: str, reached_host: str = "") -> str:
    """The address a device reaches the hub on.

    A served LAN that holds the device's own address answers first;
    otherwise the address the device actually connected to, and a served
    LAN address or the default only stand in when nothing names one.

    Args:
        runtime: The shared runtime.
        device_ip: The device's address, to pick the LAN it is on.
        reached_host: The address the device connected to.

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
    return address or reached_host or fallback or "192.168.100.1"


def record_desktop_share(runtime, device, share: dict, host: str) -> None:
    """Take one machine's word on whether its desktop is shared.

    Only a machine's own agent declares this, and only for itself: the
    device the token resolved to is the one the share is recorded against.
    The address is where its channel comes from, never one the message
    names.

    Args:
        runtime: The shared runtime.
        device: The device the token resolved to.
        share: The message's ``desktop`` section.
        host: Where this machine's channel comes from.
    """
    key = device.id
    was_sharing = any(held.device_id == key for held in runtime.device_shares.live())
    is_shared = bool(share.get("is_shared")) if isinstance(share, dict) else False
    share_id = str(share.get("share_id", "") or "") if is_shared else ""
    if is_shared and share_id and host:
        runtime.device_shares.declare(
            device_id=key,
            share_id=share_id,
            hostname=runtime.device_hostname.get(key, "") or device.name,
            host=host,
            port=int(share.get("port") or SERVICES_RDP_PORT),
            attention=str(share.get("attention", "") or ""),
            account=str(share.get("account", "") or ""),
            connected_count=int(share.get("connected_count") or 0),
        )
    else:
        runtime.device_shares.withdraw(key)
    if was_sharing != (is_shared and bool(share_id) and bool(host)):
        runtime.published_services.schedule_refresh()


def _ensure_seat_password(runtime, key: str, modules: dict) -> bool:
    """Give a device its seat password once its agent hosts RustDesk.

    The password is the hub's to make, so a machine that reports the host
    present is handed one it never typed, and the state carrying it goes
    down the moment it exists. A locked vault seals nothing and the next
    report tries again.

    Args:
        runtime: The shared runtime.
        key: The device.
        modules: The module states the report carries.

    Returns:
        True when a password was made, so the state is pushed again.
    """
    reported = modules.get(DEVICE_RDP_MODULE)
    if not isinstance(reported, dict):
        return False
    if str(reported.get("state", "")) not in CHANNEL_MODULE_PRESENT_STATES:
        return False
    return runtime.desired_states.ensure_seat_password(key)


def _settle_absent(runtime, key: str, modules: dict) -> bool:
    """Drop every module the hub wanted absent that the machine reports absent.

    Args:
        runtime: The shared runtime.
        key: The device.
        modules: The module states the report carries.

    Returns:
        True when ``modules.json`` changed, so the state is pushed again
        and the agent's copy stops naming the module.
    """
    is_changed = False
    for name, status in modules.items():
        if not isinstance(status, dict):
            continue
        if str(status.get("state", "")) != CHANNEL_MODULE_STATE_ABSENT:
            continue
        if runtime.desired_states.want_of(key, name) != CHANNEL_MODULE_STATE_ABSENT:
            continue
        if runtime.desired_states.forget_module(key, name):
            is_changed = True
    return is_changed


def _push_state(runtime, key: str) -> None:
    """Hand the device its state now; one that does not take it waits."""
    try:
        runtime.push_desired_state(key)
    except (AgentOfflineError, StreamRefusedError):
        return


def _record_machine(runtime, key: str, machine) -> None:
    """The hostname, platform, accounts and metrics of the ``machine`` section."""
    machine = machine if isinstance(machine, dict) else {}
    hostname = str(machine.get("hostname", "") or "")
    if hostname:
        runtime.device_hostname[key] = hostname
    platform = machine.get("platform")
    if isinstance(platform, dict) and platform:
        runtime.device_platform[key] = dict(platform)
    accounts = machine.get("accounts")
    if isinstance(accounts, list):
        runtime.device_accounts[key] = [str(account) for account in accounts]
    metrics = machine.get("metrics")
    runtime.device_metrics[key] = dict(metrics) if isinstance(metrics, dict) else {}


def _record_network(runtime, device, network, *, peer_host: str) -> None:
    """The address, the interfaces and the link MAC of the ``network`` section."""
    key = device.id
    network = network if isinstance(network, dict) else {}
    address = link_address(network, peer_host or runtime.device_address.get(key, ""))
    if address:
        runtime.device_address[key] = address
    interfaces = network.get("interfaces")
    if isinstance(interfaces, list):
        runtime.device_interfaces[key] = [
            dict(interface) for interface in interfaces if isinstance(interface, dict)
        ]
    link = network.get("link")
    mac = str(link.get("mac", "") or "") if isinstance(link, dict) else ""
    if mac:
        DeviceRegistry().note_machine(key, link_mac=mac)
