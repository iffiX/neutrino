"""The edition table: the one way the rest of the hub reaches a left-out feature.

A left-out feature is one the mainland edition ``cn`` builds without, by
deleting its files from the tree: the proxy and NetBird. Code outside a
feature's own files never imports them; it asks this table for the hooks
of one registration point and gets those of the present features alone.
A feature is present when its package imports. Every hook is named by its
dotted path and imported on its first lookup, so loading this file imports
no feature.

``EDITION`` is where the hub fetches from, never which features it has:
the stamp a build writes into ``_version.py``, else the ``EDITION`` file at
the root of a checkout, else ``intl``.
"""

import importlib
import importlib.util
from pathlib import Path

EDITION_INTL = "intl"
EDITION_CN = "cn"
EDITIONS = (EDITION_INTL, EDITION_CN)
# The file at the root of a checkout naming its edition.
EDITION_FILE_NAME = "EDITION"

EDITION_FEATURE_PROXY = "proxy"
EDITION_FEATURE_NETBIRD = "netbird"
# Each feature, by the package whose presence is the feature's.
EDITION_FEATURE_PACKAGES = {
    EDITION_FEATURE_PROXY: "neutrino_hub.modules.xray",
    EDITION_FEATURE_NETBIRD: "neutrino_hub.modules.netbird",
}

_PROXY = EDITION_FEATURE_PROXY
_NETBIRD = EDITION_FEATURE_NETBIRD
# Each registration point, by the hooks the features give it, in the order
# the point takes them. A hook is ``module:attribute``.
EDITION_HOOKS = {
    # web/app.py, API_ROUTERS.
    "api_routers": (
        (_NETBIRD, "neutrino_hub.web.routers.hub.overlay_netbird:router"),
        (_PROXY, "neutrino_hub.web.routers.hub.proxy:router"),
        (_PROXY, "neutrino_hub.web.routers.hub.proxy_node:router"),
    ),
    # modules/registry.py, MODULE_SPECS: ``(key, ModuleSpec fields)``.
    "module_specs": (
        (_NETBIRD, "neutrino_hub.modules.netbird.provisioner:NETBIRD_MODULE_SPEC"),
    ),
    # modules/overlay/constants.py, OVERLAY_ENGINES: ``(key, OverlayEngine
    # fields)``.
    "overlay_engines": (
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_OVERLAY_ENGINE"),
    ),
    # The overlay engines' own parts: ``(key, class)`` with ``provisioner``,
    # ``address``, ``name``, ``relayed_peer_addresses``, ``material``,
    # ``deselect`` and ``gate``.
    "overlay_parts": (
        (_NETBIRD, "neutrino_hub.modules.netbird.overlay_part:NETBIRD_OVERLAY_PART"),
    ),
    # The network modes setup and the Network page offer beyond ``router``
    # and ``server``: ``{key, summary}``.
    "router_modes": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_SIDE_GATEWAY_MODE"),
    ),
    # The router's renderers: the proxy's chains and marks, and where
    # dnsmasq forwards while the proxy takes the served networks' traffic.
    "router_nft": ((_PROXY, "neutrino_hub.modules.xray.router_part:XrayNftPart"),),
    "router_dnsmasq": (
        (_PROXY, "neutrino_hub.modules.xray.router_part:dnsmasq_upstream"),
    ),
    # Reading the proxy's routing options, its account's uid, and its DNS
    # inbound as ``(address, port)``.
    "proxy_routing": ((_PROXY, "neutrino_hub.modules.xray.router_part:read_routing"),),
    "proxy_uid": ((_PROXY, "neutrino_hub.modules.xray.router_part:lookup_xray_uid"),),
    "proxy_dns_inbound": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_DNS_INBOUND"),
    ),
    # The router's pass on macOS and Windows: the TUN step.
    "router_tun_step": ((_PROXY, "neutrino_hub.modules.tun.ops:converge_tun_step"),),
    # The interfaces and the network the hub's own machinery holds and no
    # role names: the proxy's TUN.
    "hidden_devices": (
        (_PROXY, "neutrino_hub.modules.tun.constants:TUN_DEVICE_NAMES"),
    ),
    "hidden_networks": ((_PROXY, "neutrino_hub.modules.tun.constants:TUN_NETWORK"),),
    # The programs the system firewall allows on macOS: the proxy core's,
    # and each overlay engine's as ``(key, path)``.
    "proxy_program": ((_PROXY, "neutrino_hub.modules.xray.constants:XRAY_BINARY"),),
    "overlay_programs": (
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_FIREWALL_PROGRAM"),
    ),
    # The daemons the hub runs itself: the units, the names the service
    # knows, the core daemons, and the start line of each outside Linux.
    "core_units": ((_PROXY, "neutrino_hub.modules.xray.constants:XRAY_CORE_UNIT"),),
    "optional_units": (
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_OPTIONAL_UNIT"),
    ),
    "supervised_names": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_SUPERVISED_NAMES"),
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_SUPERVISED_NAMES"),
    ),
    "child_requirements": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_CHILD_REQUIREMENTS"),
    ),
    "services": ((_PROXY, "neutrino_hub.modules.xray.constants:XRAY_SUPERVISED_NAME"),),
    # system/units.py: the unit templates the hub installs on Linux.
    "unit_templates": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_UNIT_TEMPLATE"),
    ),
    # cli/reset.py: the state files and directories a full reset clears.
    "reset_state_paths": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_NODE_HEALTH_RELATIVE"),
    ),
    "reset_state_dirs": (
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_STATE_DIR_NAME"),
    ),
    # web/constants.py: the domains a panel certificate may name.
    "panel_tls_domains": (
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_PANEL_TLS_DOMAIN"),
    ),
    "child_start_lines": (
        (_PROXY, "neutrino_hub.modules.xray.run_part:child_start_lines"),
        (_NETBIRD, "neutrino_hub.modules.netbird.run_part:child_start_lines"),
    ),
    # cli/run.py: ``nhub run --only-<name>``, the Linux children of a plain
    # ``nhub run``, and what the service does before and while it supervises.
    "run_only": ((_PROXY, "neutrino_hub.modules.xray.run_part:RUN_ONLY"),),
    "run_children": ((_PROXY, "neutrino_hub.modules.xray.run_part:RUN_CHILDREN"),),
    "service_start": (
        (_PROXY, "neutrino_hub.modules.tun.ops:withdraw_tun_on_start"),
        (_NETBIRD, "neutrino_hub.modules.netbird.run_part:make_directories"),
    ),
    "service_watcher": ((_PROXY, "neutrino_hub.modules.tun.ops:TunRouteKeeper"),),
    # cli/reset.py: what a reset withdraws first.
    "reset_withdraw": ((_PROXY, "neutrino_hub.modules.tun.ops:withdraw_tun"),),
    # cli/setup.py: the steps, the account, the answers, the config files and
    # the carried programs.
    "setup_steps": ((_PROXY, "neutrino_hub.modules.xray.setup_part:SETUP_STEPS"),),
    "setup_service_user": (
        (_PROXY, "neutrino_hub.modules.xray.setup_part:ensure_service_user"),
    ),
    "setup_answers": ((_PROXY, "neutrino_hub.modules.xray.setup_part:write_answers"),),
    "setup_config_files": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_CONFIG_FILES"),
    ),
    "setup_carried_programs": (
        (_PROXY, "neutrino_hub.modules.xray.constants:XRAY_BINARY"),
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_BINARY_PATH"),
    ),
    # cli/wizard.py and the browser's setup: the proxy screen's defaults and
    # how it reads a share link.
    "wizard_proxy": ((_PROXY, "neutrino_hub.modules.xray.setup_part:WIZARD_PROXY"),),
    # nhub apply's components, and the panel's converge step for them.
    "apply_components": (
        (_PROXY, "neutrino_hub.modules.xray.apply_part:XrayApplyComponent"),
    ),
    # web/panel_runtime.py: the proxy's live objects and its part of a
    # converge.
    "panel_proxy": ((_PROXY, "neutrino_hub.web.routers.hub.proxy:ProxyPanelPart"),),
    # The live statistics frame: the proxy's fields, and which outbounds
    # are exits.
    "stats_readings": (
        (_PROXY, "neutrino_hub.web.routers.hub.proxy_node:stats_readings"),
    ),
    "exit_tag_filter": (
        (_PROXY, "neutrino_hub.web.routers.hub.proxy_node:is_exit_tag"),
    ),
    # The vault's secrets the exit nodes name: how many name each, and
    # taking one off every node.
    "secret_node_counts": (
        (_PROXY, "neutrino_hub.modules.xray.node_secrets:node_secret_counts"),
    ),
    "secret_node_clear": (
        (_PROXY, "neutrino_hub.modules.xray.node_secrets:clear_node_secret"),
    ),
    # Settings' About card: the components the tree carries.
    "about_versions": ((_PROXY, "neutrino_hub.web.routers.hub.proxy:about_versions"),),
    "about_components": (
        (_PROXY, "neutrino_hub.web.routers.hub.proxy:PROXY_ABOUT_COMPONENTS"),
        (_NETBIRD, "neutrino_hub.modules.netbird.constants:NETBIRD_ABOUT"),
    ),
}

_present: dict = {}


def has_feature(name: str) -> bool:
    """Whether a left-out feature is in this tree.

    Args:
        name: ``proxy`` or ``netbird``.

    Returns:
        True when the feature's package imports.

    Raises:
        KeyError: When ``name`` is no feature.
    """
    package = EDITION_FEATURE_PACKAGES[name]
    if package not in _present:
        try:
            _present[package] = importlib.util.find_spec(package) is not None
        except ImportError:
            _present[package] = False
    return _present[package]


def hooks(point: str) -> tuple:
    """The hooks the present features give one registration point.

    Args:
        point: A key of :data:`EDITION_HOOKS`.

    Returns:
        Each present feature's hook, imported, in the table's order; empty
        when no present feature gives the point one.

    Raises:
        KeyError: When ``point`` is no registration point.
    """
    return tuple(
        _load(target)
        for feature, target in EDITION_HOOKS[point]
        if has_feature(feature)
    )


def hook(point: str):
    """The one hook a registration point takes, when a present feature gives it.

    Args:
        point: A key of :data:`EDITION_HOOKS`.

    Returns:
        The first present feature's hook, or None.

    Raises:
        KeyError: When ``point`` is no registration point.
    """
    found = hooks(point)
    return found[0] if found else None


def _load(target: str):
    """Import one hook by its ``module:attribute`` path."""
    module_name, _, attribute = target.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def _checkout_edition() -> str:
    """The edition the root ``EDITION`` file of a checkout names.

    Returns:
        ``intl`` or ``cn``; ``intl`` when the file is missing or names
        neither.
    """
    path = Path(__file__).resolve().parents[2] / EDITION_FILE_NAME
    try:
        named = path.read_text(encoding="utf-8").strip()
    except OSError:
        return EDITION_INTL
    return named if named in EDITIONS else EDITION_INTL


try:  # Written into the tree when a package is built.
    from neutrino_hub._version import EDITION
except ImportError:
    EDITION = _checkout_edition()
