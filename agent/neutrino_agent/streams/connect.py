"""Which ports this machine publishes now, for the transport's ``port`` question.

The hub opens ``connect {port, protocol}`` for a client that asked for a
service this machine publishes. The agent's transport serves the stream
itself: it asks the agent ``port`` whether the port is published on the
stream's protocol, dials ``127.0.0.1:<port>``, or the address a container
port is published on when it names one, and refuses every other port
``port_not_published {port}`` before anything is dialled. Pure: reads the
report and the hub's last state.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ipaddress
import urllib.parse

from neutrino_agent.constants import AGENT_CONNECT_LOOPBACK, AGENT_CONNECT_TCP

# The port the file share answers SMB on, on every system.
SMB_PORT = 445
# The port a web url stands for when it names none, by its scheme.
SCHEME_PORTS = {"http": 80, "https": 443}
# The module states under which the hub has configured a module.
CONFIGURED_STATES = ("stopped", "running")
# The modules whose configured instances each answer on the port the agent
# took for them, which their details report.
INSTANCE_MODULES = ("vscode", "cloudcli", "code_server", "codeg", "siyuan")
# The modules whose instances publish their port only while they run.
RUNNING_INSTANCE_MODULES = ("ssh_server",)
# The container modules whose page the agent's forwarder serves at the port
# their details report.
FORWARDED_MODULES = ("hermes_webui", "ayakaleaf")


def published_ports(
    modules: dict,
    desired_modules: dict,
    desktop: dict,
    protocol: str = AGENT_CONNECT_TCP,
) -> dict:
    """Every port this machine publishes now on one protocol, each to the
    address it is dialled on.

    Args:
        modules: The modules section of this machine's report, ``{name:
            {state, details, ...}}``.
        desired_modules: The modules section of the hub's last state,
            ``{name: {want, config, ...}}``.
        desktop: The desktop section of this machine's report.
        protocol: ``tcp`` or ``udp``.

    Returns:
        Port to address. On TCP: 445 while the file share reports a share,
        the desktop's direct port while it is shared, the Gitea module's
        port and its own SSH server's while it reports a url, each
        configured VS Code, code-server, CloudCLI, Codeg or SiYuan instance's port,
        each running SSH server instance's port, the port of a container
        module's forwarder, and each port a running container publishes on
        TCP. On UDP: each port a running container publishes on UDP, and
        nothing else. The port a hub container's ``page_port`` is published
        at is never one. A container's port goes to the one address it is
        published on when it names one; every other to loopback. A binding
        that names no protocol is TCP.
    """
    if protocol != AGENT_CONNECT_TCP:
        return _container_ports(modules, desired_modules, protocol)
    ports: dict = {}
    samba = _configured(modules.get("samba"))
    if samba is not None and samba.get("shares"):
        ports[SMB_PORT] = AGENT_CONNECT_LOOPBACK
    if isinstance(desktop, dict) and desktop.get("is_shared"):
        port = _port(desktop.get("port"))
        if port:
            ports[port] = AGENT_CONNECT_LOOPBACK
    gitea = _configured(modules.get("gitea"))
    if gitea is not None and gitea.get("url"):
        for port in (
            url_port(str(gitea.get("url", "") or "")),
            _port(gitea.get("port")),
            _port(gitea.get("ssh_listen_port")),
        ):
            if port:
                ports[port] = AGENT_CONNECT_LOOPBACK
    for name in INSTANCE_MODULES + RUNNING_INSTANCE_MODULES:
        details = _configured(modules.get(name))
        for instance in (details or {}).get("instances") or []:
            if not isinstance(instance, dict):
                continue
            if name in RUNNING_INSTANCE_MODULES and not instance.get("is_running"):
                continue
            port = _port(instance.get("port"))
            if port:
                ports[port] = AGENT_CONNECT_LOOPBACK
    for name in FORWARDED_MODULES:
        details = _configured(modules.get(name))
        port = _port((details or {}).get("port"))
        if port:
            ports[port] = AGENT_CONNECT_LOOPBACK
    ports.update(_container_ports(modules, desired_modules, protocol))
    return ports


def url_port(url: str) -> int:
    """The port a url names, 80 or 443 by its scheme when it names none.

    Args:
        url: The url.

    Returns:
        The port; 0 for a url that names neither a port nor a known scheme.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return 0
    return port or SCHEME_PORTS.get(parts.scheme, 0)


def dial_address(address: str) -> str:
    """Where a port published on one address is dialled.

    Args:
        address: The address a container port is published on, empty for
            every address.

    Returns:
        Loopback for every address and for no address; the address itself
        otherwise.
    """
    try:
        if ipaddress.ip_address(address).is_unspecified:
            return AGENT_CONNECT_LOOPBACK
    except ValueError:
        return AGENT_CONNECT_LOOPBACK
    return address


def _container_ports(modules: dict, desired_modules: dict, protocol: str) -> dict:
    """The ports the Podman module's running containers publish on one protocol,
    the port a hub container's ``page_port`` is published at left out."""
    ports: dict = {}
    podman = _configured(modules.get("podman"))
    pages = _page_ports(desired_modules)
    for container in (podman or {}).get("containers") or []:
        if not isinstance(container, dict) or not container.get("is_running"):
            continue
        page_hosts = _page_hosts(container, pages.get(str(container.get("name", ""))))
        for binding in container.get("host_bindings") or []:
            if not isinstance(binding, dict):
                continue
            if str(binding.get("protocol", "") or AGENT_CONNECT_TCP) != protocol:
                continue
            port = _port(binding.get("port"))
            if port and port not in page_hosts:
                ports[port] = dial_address(str(binding.get("address", "") or ""))
    return ports


def _page_ports(desired_modules: dict) -> dict:
    """Each hub container's ``page_port`` the state names, by container name."""
    entry = desired_modules.get("podman")
    config = entry.get("config") if isinstance(entry, dict) else None
    if not isinstance(config, dict):
        return {}
    pages = {}
    for container in config.get("hub_containers") or []:
        if isinstance(container, dict) and _port(container.get("page_port")):
            pages[str(container.get("name", ""))] = container["page_port"]
    return pages


def _page_hosts(container: dict, page_port) -> set:
    """The host ports one reported container publishes its ``page_port`` at."""
    if not page_port:
        return set()
    hosts = set()
    for mapping in container.get("ports") or []:
        host, _, rest = str(mapping).partition(":")
        inside = rest.partition("/")[0]
        if host.isdigit() and inside == str(page_port):
            hosts.add(int(host))
    return hosts


def _configured(status) -> "dict | None":
    """A reported module's details while the hub has configured it, else None."""
    if not isinstance(status, dict) or status.get("state") not in CONFIGURED_STATES:
        return None
    details = status.get("details")
    return details if isinstance(details, dict) else {}


def _port(value) -> int:
    """A port number, 0 for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 < value < 65536 else 0
