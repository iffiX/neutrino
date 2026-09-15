"""What the hub keeps of an agent's hello and its reports.

An agent's socket opens with one ``hello`` and then carries a ``report``
every few seconds. Both land in the runtime's memory alone, which is what
the panel reads: a machine's presence is true only while this hub runs.

A report writes two things. The seat password: a machine reporting the
remote desktop host installed is given one, sealed under the vault's data
key, the first time it says so. And the MAC its socket runs on, noted on
the device's row when it is new.
"""

import ipaddress

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_STATE_INSTALLED,
    DEVICE_RDP_MODULE,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.constants import SERVICES_RDP_PORT


def record_hello(
    runtime, device, hello: dict, *, peer_host: str, reached_host: str
) -> None:
    """Take what a machine says it is when its socket opens.

    Args:
        runtime: The shared runtime.
        device: The device the token resolved to.
        hello: The hello message.
        peer_host: Where the socket comes from.
        reached_host: The address the machine connected to.
    """
    key = device.id
    platform = hello.get("platform")
    if isinstance(platform, dict) and platform:
        runtime.device_platform[key] = dict(platform)
    hostname = str(hello.get("hostname", "") or "")
    if hostname:
        runtime.device_hostname[key] = hostname
    _record_machine(runtime, key, hello, peer_host=peer_host)
    _record_reinstall(runtime, key, hello)
    runtime.device_hub_host[key] = device_host(
        runtime, runtime.device_address.get(key, ""), reached_host
    )


def record_report(runtime, device, report: dict) -> None:
    """Take one report: what is true of the machine right now.

    Args:
        runtime: The shared runtime.
        device: The device the socket belongs to.
        report: The report message.
    """
    key = device.id
    metrics = report.get("metrics")
    runtime.device_metrics[key] = dict(metrics) if isinstance(metrics, dict) else {}
    modules = report.get("modules")
    modules = dict(modules) if isinstance(modules, dict) else {}
    runtime.device_modules[key] = modules
    # Software turning up on the machine anyway settles a standing failure.
    runtime.agent_module_orders.note_reported_states(key, modules)
    _ensure_seat_password(runtime, key, modules)
    platform = report.get("platform")
    if isinstance(platform, dict) and platform:
        runtime.device_platform[key] = dict(platform)
    _record_machine(runtime, key, report, peer_host="")
    _note_link(device, report.get("network"))
    _record_reinstall(runtime, key, report)
    record_desktop_share(
        runtime, device, report.get("rdp") or {}, runtime.device_address.get(key, "")
    )
    error = report.get("last_error")
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
        share: The message's desktop declaration.
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


def _ensure_seat_password(runtime, key: str, modules: dict) -> None:
    """Give a device its seat password once its agent hosts RustDesk.

    The password is the hub's to make, so a machine that reports the host
    installed is handed one it never typed, and the state carrying it goes
    down the moment it exists. A locked vault seals nothing and the next
    report tries again; a device that does not take the state is left for
    the next push.

    Args:
        runtime: The shared runtime.
        key: The device.
        modules: The module states the report carries.
    """
    reported = modules.get(DEVICE_RDP_MODULE)
    if not isinstance(reported, dict):
        return
    if str(reported.get("state", "")) != DEVICE_MODULE_STATE_INSTALLED:
        return
    if not runtime.desired_states.ensure_seat_password(key):
        return
    try:
        runtime.push_desired_state(key)
    except (AgentOfflineError, StreamRefusedError):
        return


def _record_reinstall(runtime, key: str, message: dict) -> None:
    """Keep the machine's word on the install it came back from.

    The hello carries it before the first report does, so the reinstall
    task can read it the moment the socket is up.

    Args:
        runtime: The shared runtime.
        key: The device.
        message: The hello or the report.
    """
    session = runtime.agent_sessions.get(key)
    if session is None:
        return
    record = message.get("last_reinstall")
    if isinstance(record, dict) and record:
        session.report["last_reinstall"] = dict(record)
    else:
        session.report.pop("last_reinstall", None)


def _record_machine(runtime, key: str, message: dict, *, peer_host: str) -> None:
    """The accounts, the address and the interfaces a message carries."""
    accounts = message.get("accounts")
    if isinstance(accounts, list):
        runtime.device_accounts[key] = [str(account) for account in accounts]
    network = message.get("network")
    network = network if isinstance(network, dict) else {}
    address = link_address(network, peer_host or runtime.device_address.get(key, ""))
    if address:
        runtime.device_address[key] = address
    interfaces = network.get("interfaces")
    if isinstance(interfaces, list):
        runtime.device_interfaces[key] = [
            dict(interface) for interface in interfaces if isinstance(interface, dict)
        ]


def _note_link(device, network) -> None:
    """Put the MAC the socket runs on onto the device's row when it is new."""
    link = network.get("link") if isinstance(network, dict) else None
    mac = str(link.get("mac", "") or "") if isinstance(link, dict) else ""
    if mac:
        DeviceRegistry().note_machine(device.id, link_mac=mac)
