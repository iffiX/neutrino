"""What the hub keeps of an agent's hello and its reports.

An agent's socket opens with one ``hello`` and then carries a ``report``
every few seconds. The hello is the moment the device is seen, so it is the
one point that writes ``config/``: the registry's last-seen stamp. A report
lands only in the runtime's memory, which is what the panel reads.

Not pure: writes the device registry on hello and on the socket ending.
"""

import ipaddress
from datetime import datetime, timezone

from neutrino_hub.modules.services.constants import SERVICES_RDP_PORT


def record_hello(
    runtime, registry, device, hello: dict, *, peer_host: str, reached_host: str
) -> None:
    """Take what a machine says it is when its socket opens.

    Args:
        runtime: The shared runtime.
        registry: The device registry.
        device: The device the token resolved to.
        hello: The hello message.
        peer_host: Where the socket comes from.
        reached_host: The address the machine connected to.
    """
    key = device.mac_address
    platform = hello.get("platform")
    if isinstance(platform, dict) and platform:
        runtime.client_platform[key] = dict(platform)
    hostname = str(hello.get("hostname", "") or "")
    if hostname:
        runtime.client_hostname[key] = hostname
    _record_machine(runtime, key, hello, peer_host=peer_host)
    runtime.client_device_host[key] = device_host(
        runtime, runtime.client_address.get(key, ""), reached_host
    )
    registry.record_heartbeat(
        key, version=str(hello.get("client_version", "") or ""), seen_at=_now()
    )


def record_report(runtime, device, report: dict) -> None:
    """Take one report: what is true of the machine right now.

    Args:
        runtime: The shared runtime.
        device: The device the socket belongs to.
        report: The report message.
    """
    key = device.mac_address
    metrics = report.get("metrics")
    runtime.client_metrics[key] = dict(metrics) if isinstance(metrics, dict) else {}
    modules = report.get("modules")
    modules = dict(modules) if isinstance(modules, dict) else {}
    runtime.client_modules[key] = modules
    # Software turning up on the machine anyway settles a standing failure.
    runtime.agent_module_orders.note_reported_states(key, modules)
    platform = report.get("platform")
    if isinstance(platform, dict) and platform:
        runtime.client_platform[key] = dict(platform)
    _record_machine(runtime, key, report, peer_host="")
    record_rdp_share(
        runtime, device, report.get("rdp") or {}, runtime.client_address.get(key, "")
    )
    error = report.get("last_error")
    if isinstance(error, dict) and error.get("code"):
        runtime.client_last_error[key] = {
            "code": str(error.get("code")),
            "params": dict(error.get("params") or {}),
        }
    else:
        runtime.client_last_error.pop(key, None)


def record_offline(runtime, registry, device, *, version: str) -> None:
    """Take a socket ending: the device was last seen now.

    Args:
        runtime: The shared runtime.
        registry: The device registry.
        device: The device whose socket ended.
        version: The agent release it reported.
    """
    key = device.mac_address
    registry.record_heartbeat(key, version=version, seen_at=_now())
    record_rdp_share(runtime, device, {}, runtime.client_address.get(key, ""))


def device_address(reported: list, mac_address: str, peer_host: str) -> str:
    """Where a machine is, out of everything it carries.

    The address on the machine's identity MAC wins: the interface the hub
    keys the device by. The connection's peer address stands in where
    nothing matches.

    Args:
        reported: The message's ``addresses``, ``[{"mac", "address"}]``.
        mac_address: The device's identity MAC.
        peer_host: Where the socket comes from.

    Returns:
        The address, empty when there is none to be had.
    """
    wanted = mac_address.lower()
    for entry in reported or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("mac", "")).lower() != wanted:
            continue
        address = str(entry.get("address", "") or "")
        if address:
            return address
    return peer_host


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


def record_rdp_share(runtime, device, share: dict, host: str) -> None:
    """Take one machine's word on whether its desktop is shared.

    Only a machine's own agent declares this, and only for itself: the
    device the token resolved to is the one the share is recorded against.
    The address is where its channel comes from, never one the message
    names.

    Args:
        runtime: The shared runtime.
        device: The device the token resolved to.
        share: The message's ``rdp``.
        host: Where this machine's channel comes from.
    """
    key = device.mac_address
    was_sharing = any(held.mac_address == key for held in runtime.device_shares.live())
    is_shared = bool(share.get("is_shared")) if isinstance(share, dict) else False
    share_id = str(share.get("share_id", "") or "") if is_shared else ""
    if is_shared and share_id and host:
        runtime.device_shares.declare(
            mac_address=key,
            share_id=share_id,
            hostname=runtime.client_hostname.get(key, "") or device.name,
            host=host,
            port=int(share.get("port") or SERVICES_RDP_PORT),
            attention=str(share.get("attention", "") or ""),
        )
    else:
        runtime.device_shares.withdraw(key)
    if was_sharing != (is_shared and bool(share_id) and bool(host)):
        # The published list is cached for a few seconds; a share appearing
        # or ending is what a person is watching for, so it recomposes now.
        runtime.published_services.expire()


def _record_machine(runtime, key: str, message: dict, *, peer_host: str) -> None:
    """The accounts and the address a hello and a report both carry."""
    accounts = message.get("accounts")
    if isinstance(accounts, list):
        runtime.client_accounts[key] = [str(account) for account in accounts]
    address = device_address(
        message.get("addresses") or [],
        key,
        peer_host or runtime.client_address.get(key, ""),
    )
    if address:
        runtime.client_address[key] = address


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
