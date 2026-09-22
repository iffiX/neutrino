"""What the hub keeps of an agent's hello and its reports.

An agent's socket opens with one ``hello`` and then carries a ``report``
every few seconds. Both land in the runtime's memory alone, which is what
the panel reads: a machine's presence is true only while this hub runs.

A report is read by its sections: ``machine``, ``network``, ``modules``,
``desktop`` and ``error``. It writes four things. The seat password: a
machine reporting the remote desktop host present is given one, sealed
under the vault's data key, the first time it says so. The MAC its socket
runs on, noted on the device's row when it is new. ``modules.json``: a
module the hub wanted ``absent`` that the machine now reports absent is
settled there, so the hub's state stops naming software it took off while
the module's row goes on saying what the person asked for. And, at the
first report on a socket, the hub's record of each module it holds no
``want`` for: what the machine hosts becomes the hub's configuration and
its want, and the hub's copy is the one truth from then on.
"""

import logging

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_MODULE_PRESENT_STATES,
    CHANNEL_MODULE_STATE_ABSENT,
    CHANNEL_MODULE_STATE_INSTALLED,
    CHANNEL_MODULE_STATE_RUNNING,
    CHANNEL_MODULE_STATE_STOPPED,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_GITEA_MODULE,
    DEVICE_RDP_MODULE,
)
from neutrino_hub.modules.devices.module_import import (
    MODULE_IMPORTS,
    import_module_config,
)
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.services.constants import SERVICES_RDP_PORT
from neutrino_hub.modules.services.host_scope import scope_of

LOGGER = logging.getLogger(__name__)


def record_hello(
    runtime, device, *, name: str, peer_host: str, reached_host: str
) -> None:
    """Take what a machine says it is when its socket opens.

    Args:
        runtime: The shared runtime.
        device: The device the token resolved to.
        name: What the hello called the machine.
        peer_host: Where the socket comes from; the device's address until
            a report names one, and what settles the scope it arrived from.
        reached_host: The address the machine connected to.
    """
    key = device.id
    if name:
        runtime.device_hostname[key] = name
    if peer_host:
        runtime.device_address[key] = peer_host
    runtime.device_scope[key] = scope_of(
        runtime.device_address.get(key, ""), reached_host, runtime.host_scopes()
    )


def record_report(
    runtime, device, report: dict, *, peer_host: str = "", is_first: bool = False
) -> None:
    """Take one report: what is true of the machine right now.

    Args:
        runtime: The shared runtime.
        device: The device the socket belongs to.
        report: The report message.
        peer_host: Where the socket comes from, the address recorded when
            the report's link names none.
        is_first: Whether this is the socket's first report, at which the
            hub's record of each module it holds no want for is made to
            match the machine.
    """
    key = device.id
    _record_machine(runtime, key, report.get("machine"))
    _record_network(runtime, device, report.get("network"), peer_host=peer_host)
    modules = report.get("modules")
    modules = dict(modules) if isinstance(modules, dict) else {}
    runtime.device_modules[key] = modules
    is_settled = _settle_absent(runtime, key, modules)
    is_adopted = is_first and _adopt_modules(runtime, key, modules)
    is_seated = _ensure_seat_password(runtime, key, modules)
    if is_settled or is_adopted or is_seated:
        _push_state(runtime, key)
    if is_adopted:
        runtime.published_services.schedule_refresh()
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
    """Settle every module the hub wanted absent that the machine reports absent.

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
        if runtime.desired_states.settle_want(key, name):
            is_changed = True
    return is_changed


def _adopt_modules(runtime, key: str, modules: dict) -> bool:
    """Make the hub's record of each module it holds no want for match the machine.

    A module with an import and no ``want`` is taken over from what the
    machine reports: one the hub's mark says is configured (``stopped`` or
    ``running``) is wanted as it reports, its configuration imported when
    the hub holds none; one installed by hand is imported, and wanted
    ``running`` or ``stopped`` by whether its unit is active. An import
    that finds nothing leaves the module as it is, and Gitea is taken over
    only while the hub still holds the secrets its instance signs with.

    Args:
        runtime: The shared runtime.
        key: The device.
        modules: The module states the report carries.

    Returns:
        True when a want or a configuration was written, so the state is
        pushed again and the published list recomposed.
    """
    store = runtime.desired_states
    is_changed = False
    for name, status in modules.items():
        if name not in MODULE_IMPORTS or not isinstance(status, dict):
            continue
        state = str(status.get("state", ""))
        if state not in CHANNEL_MODULE_PRESENT_STATES:
            continue
        if store.want_of(key, name):
            continue
        if name == DEVICE_GITEA_MODULE and not store.has_gitea_secrets(key):
            continue
        if state == CHANNEL_MODULE_STATE_INSTALLED:
            if not _import(store, key, name, status):
                continue
            want = (
                CHANNEL_MODULE_STATE_RUNNING
                if status.get("is_active")
                else CHANNEL_MODULE_STATE_STOPPED
            )
        else:
            if not store.read(key, name) and not _import(store, key, name, status):
                continue
            want = state
        store.set_want(key, name, want)
        LOGGER.info("device %s: %s reported %s, adopted as %s", key, name, state, want)
        is_changed = True
    return is_changed


def _import(store, key: str, name: str, status: dict) -> bool:
    """Write what one module's report amounts to; False when it amounts to nothing."""
    details = status.get("details")
    config = import_module_config(name, details if isinstance(details, dict) else {})
    if not config:
        return False
    store.write(key, name, config)
    return True


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
