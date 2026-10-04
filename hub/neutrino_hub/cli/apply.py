"""Render every generated config from ``config/``, validate it, and apply it.

This is the command-line half of the pipeline the web panel drives. Run it after
editing anything under ``config/`` by hand:

    sudo nhub apply               # render, validate, apply all
    nhub apply --dry-run          # render and print, no effects
    sudo nhub apply --only router
    sudo nhub apply --only overlay

The unit files come with it. They ship in the package rather than being
rendered from ``config/``, so an upgrade that changes one lands here: writing
them is part of making the box true, and a unit already current is left
alone.

The apply runs the panel's converge steps in the panel's order: the enabled
overlays start, then the routing state, dnsmasq and xray, and the overlays
turned off stop last. The two pushes to devices and clients are the panel's;
a peer is handed its state when it next reports to a running panel.
"""

import argparse
import json
import subprocess
import sys
from socket import gethostname

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.easytier.constants import (
    EASYTIER_CORE_PATH,
    EASYTIER_DROPIN_DIR_NAME,
    EASYTIER_DROPIN_NAME,
    EASYTIER_GENERATED_NAME,
)
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.easytier.renderer import render_arguments
from neutrino_hub.modules.easytier.renderer import render_config as render_easytier
from neutrino_hub.modules.easytier.renderer import render_dropin
from neutrino_hub.system.constants import (
    SYSTEM_START_LINE_DROPIN_NAME,
    SYSTEM_SYSTEMD_DIR,
)
from neutrino_hub.system.systemd_ctl import start_line_dropin
from neutrino_hub.modules.overlay.config import enabled_providers
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER
from neutrino_hub.modules.overlay.constants import OVERLAY_RELAY_UNIT
from neutrino_hub.modules.overlay.ops import OverlaySwitcher, overlay_devices
from neutrino_hub.modules.overlay.relay_config import read_relay
from neutrino_hub.modules.overlay.relay_ops import (
    OverlayRelayApplier,
    is_relay_configured,
    known_hosts_path,
    ssh_path,
)
from neutrino_hub.modules.overlay.relay_ops import key_path as relay_key_path
from neutrino_hub.modules.overlay.relay_renderer import OverlayRelayRenderer
from neutrino_hub.modules.router.constants import (
    ROUTER_DNSMASQ_PATH,
    ROUTER_NFT_PATH,
    ROUTER_STEP_UNCHANGED,
)
from neutrino_hub.modules.router.controller import (
    RouterStateController,
    engine_cgroups,
    failure_text,
)
from neutrino_hub.modules.router.dnsmasq_renderer import RouterDnsmasqRenderer
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.routes import (
    install_dnsmasq,
    lookup_xray_uid,
    read_network_resolvers,
    record_network_resolvers,
)
from neutrino_hub.modules.router.supplicant import (
    write_config as write_supplicant_config,
)
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_GENERATED_DIR
from neutrino_hub.platforms.detect import is_linux, process_controller
from neutrino_hub.system.units import SystemdUnitInstaller
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_GENERATED_NAME
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier
from neutrino_hub.modules.cliproxyapi.management_key import (
    ensure_management_key,
    write_working_key,
)
from neutrino_hub.web.agent_tls import ensure_certificate, write_served_key
from neutrino_hub.web.constants import (
    WEB_AGENT_TLS_CERT_PATH,
    WEB_DEFAULT_AGENT_LISTEN_PORT,
    WEB_IDENTITY_FILE,
    WEB_PANEL_TLS_SERVED_CERT_PATH,
)
from neutrino_hub.web.identity import ensure_hub_identity
from neutrino_hub.web.panel_tls import ensure_served
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.modules.tun.ops import egress_interface
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.constants import XRAY_CONFIG_PATH
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_health import XrayNodeHealthStore
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets

# --- config ---
COMPONENTS = ("router", "xray", "dnsmasq", "cliproxyapi", "overlay")


def main() -> int:
    """Render, validate, and apply the generated configuration.

    Returns:
        Process exit status: 0 on success, 1 on any failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=COMPONENTS,
        action="append",
        help="render and apply only this component; repeatable (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render and print the artifacts without writing or applying them",
    )
    parser.add_argument(
        "--skip-apply",
        action="store_true",
        help="write the generated files but do not restart any service",
    )
    args = parser.parse_args()
    selected = tuple(args.only) if args.only else COMPONENTS

    try:
        artifacts = _render(selected)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {command_failure_text(error)}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_artifacts(artifacts)
        return 0

    try:
        if ensure_certificate():
            print(f"agent certificate generated at {WEB_AGENT_TLS_CERT_PATH}")
        write_served_key()
    except (OSError, ValueError) as error:
        code = getattr(error, "code", "agent_tls_key_unavailable")
        print(
            f'error: {{"code": "{code}"}}: the agent channel has no served key '
            f"({error})",
            file=sys.stderr,
        )

    try:
        if ensure_served():
            print(f"panel certificate issued at {WEB_PANEL_TLS_SERVED_CERT_PATH}")
    except (OSError, ValueError) as error:
        code = getattr(error, "code", "panel_tls_unavailable")
        print(
            f'error: {{"code": "{code}"}}: the panel certificate is not ready '
            f"({error})",
            file=sys.stderr,
        )

    try:
        if ensure_hub_identity():
            print(f"hub identity generated at {UTILS_CONFIG_DIR / WEB_IDENTITY_FILE}")
    except (OSError, ValueError) as error:
        print(f"error: the hub has no identity ({error})", file=sys.stderr)

    try:
        removed = _forget_orphan_device_dirs()
        if removed:
            print(f"orphan device directories removed: {', '.join(removed)}")
    except OSError as error:
        print(f"error: device directories not swept ({error})", file=sys.stderr)

    try:
        if ensure_management_key():
            print("AI gateway management key generated")
        write_working_key()
    except (OSError, ValueError) as error:
        code = getattr(error, "code", "management_key_unavailable")
        print(
            f'error: {{"code": "{code}"}}: the AI gateway has no management key '
            f"({error}); usage metering stays off",
            file=sys.stderr,
        )

    try:
        _write(artifacts, is_apply_skipped=args.skip_apply)
        if not args.skip_apply:
            units = SystemdUnitInstaller().install() if is_linux() else []
            if units:
                print(f"units refreshed: {', '.join(units)}")
            _apply(artifacts)
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"error: {command_failure_text(error)}", file=sys.stderr)
        return 1

    print(f"rendered and applied: {', '.join(sorted(artifacts))}")
    return 0


def _render(selected: tuple[str, ...]) -> dict:
    network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
    routing = read_config("xray/routing.json")
    artifacts: dict = {}
    if "xray" in selected or "dnsmasq" in selected:
        artifacts["network_resolvers"] = read_network_resolvers(network)

    if "xray" in selected:
        node_list = XrayNodeList.from_dict(read_config("xray/nodes.json"))
        resolve_node_secrets(node_list)
        artifacts["xray"] = XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
            down_tags=_down_tags(),
            is_transparent=is_linux(),
            egress_interface=egress_interface(routing),
            network_resolvers=artifacts["network_resolvers"],
        ).render()
    if "router" in selected and not is_linux():
        artifacts["router"] = ""
    elif "router" in selected:
        artifacts["router"] = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
            overlay_devices=overlay_devices(network),
            engine_cgroups=list(engine_cgroups(routing)),
        ).render()
    if "dnsmasq" in selected:
        artifacts["dnsmasq"] = RouterDnsmasqRenderer(
            network=network,
            routing=routing,
            network_resolvers=artifacts["network_resolvers"],
        ).render()
    if "cliproxyapi" in selected:
        gateway = CliproxyApiConfigApplier()
        if not gateway.is_installed:
            print("cliproxyapi: not installed, skipping")
        else:
            artifacts["cliproxyapi"] = gateway.render_with_stored_key()
    if "overlay" in selected:
        artifacts["overlay"] = network
        easytier = read_easytier()
        if OVERLAY_EASYTIER not in enabled_providers(network):
            print("easytier: not enabled, skipping")
        elif not easytier.is_configured:
            print("easytier: nothing configured, skipping")
        else:
            artifacts["easytier"] = easytier
        artifacts["relay"] = read_relay()
    return artifacts


def _down_tags() -> set[str]:
    """The outbound tags whose newest stored measurement failed."""
    store = XrayNodeHealthStore()
    store.load()
    return {tag for tag, health in store.health().items() if health.is_down}


def _forget_orphan_device_dirs() -> list:
    """Delete every ``config/devices/`` directory no stored device names."""
    stored = {device.id for device in DeviceRegistry().all_stored()}
    return DesiredStateStore().forget_orphans(stored)


def _print_artifacts(artifacts: dict) -> None:
    if "network_resolvers" in artifacts:
        rows = artifacts["network_resolvers"]
        print("--- the network's resolvers ---")
        print(", ".join(f"{row['address']}#{row['port']}" for row in rows))
        print()
    if "xray" in artifacts:
        print(f"--- {XRAY_CONFIG_PATH} ---")
        print(json.dumps(artifacts["xray"], indent=2))
    if artifacts.get("router"):
        print(f"\n--- {ROUTER_NFT_PATH} ---")
        print(artifacts["router"])
    if "dnsmasq" in artifacts:
        print(f"\n--- {ROUTER_DNSMASQ_PATH} ---")
        print(artifacts["dnsmasq"])
    if "cliproxyapi" in artifacts:
        print(f"\n--- {UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME} ---")
        print(artifacts["cliproxyapi"])
    if "overlay" in artifacts:
        enabled = enabled_providers(artifacts["overlay"])
        print(f"\n--- overlays enabled: {', '.join(enabled) or 'none'} ---")
    if "easytier" in artifacts:
        # The rendered file carries the network secret, which is the key the
        # whole network is encrypted under. A dry run prints what a person
        # asked to see, not that.
        overlay = artifacts["easytier"]
        network_path = UTILS_GENERATED_DIR / EASYTIER_GENERATED_NAME
        if not overlay.is_console_mode:
            print(f"\n--- {network_path} ---")
            print(
                render_easytier(
                    overlay, secret="<network secret>", hostname=gethostname()
                )
            )
        print(
            f"\n--- {SYSTEM_SYSTEMD_DIR / EASYTIER_DROPIN_DIR_NAME / EASYTIER_DROPIN_NAME} ---"
        )
        arguments = render_arguments(
            overlay, config_server="<console address>", config_path=str(network_path)
        )
        print(render_dropin(arguments, core_path=str(EASYTIER_CORE_PATH)), end="")
    if "relay" in artifacts:
        relay = artifacts["relay"]
        if not relay.is_enabled or not is_relay_configured(relay):
            print("\n--- relay: off or not configured ---")
        else:
            argv = OverlayRelayRenderer(
                ssh_path=ssh_path() or "ssh",
                key_path=str(relay_key_path()),
                known_hosts_path=str(known_hosts_path()),
                agent_port=_agent_port(),
            ).render(relay)
            dropin = SYSTEM_SYSTEMD_DIR / f"{OVERLAY_RELAY_UNIT}.d"
            print(f"\n--- {dropin / SYSTEM_START_LINE_DROPIN_NAME} ---")
            print(start_line_dropin(argv, {}, None), end="")


def _write(artifacts: dict, *, is_apply_skipped: bool) -> None:
    """Write what has to be on disk before anything is restarted.

    Args:
        artifacts: The rendered artifacts, by component.
        is_apply_skipped: Whether this run restarts nothing. dnsmasq's file is
            written here only then, because the apply installs it through
            `install_dnsmasq`, which writes and restarts in one step.
    """
    if "network_resolvers" in artifacts:
        record_network_resolvers(artifacts["network_resolvers"])
    if "xray" in artifacts:
        # Validates before writing, and must happen even with --skip-apply:
        # the xray unit points at this file, so systemd cannot start the
        # service until it exists.
        XrayConfigApplier().write(artifacts["xray"])
    if "dnsmasq" in artifacts and is_apply_skipped:
        write_generated(ROUTER_DNSMASQ_PATH, artifacts["dnsmasq"])


def _apply(artifacts: dict) -> None:
    switcher = OverlaySwitcher()
    if "overlay" in artifacts:
        for note in switcher.start(artifacts["overlay"]):
            print(note)
    router_failure = ""
    if "router" in artifacts:
        # The same pass the resident router unit and the panel run, under the
        # same lock; every step is tried, and the failures are raised once
        # the other components have been applied too.
        results = RouterStateController().reconcile()
        for result in results:
            if result.state != ROUTER_STEP_UNCHANGED:
                print(result.describe())
        router_failure = failure_text(results)
    if "dnsmasq" in artifacts and is_linux():
        print(
            "dnsmasq restarted"
            if install_dnsmasq(artifacts["dnsmasq"])
            else "dnsmasq unchanged"
        )
    if "xray" in artifacts:
        # _write already validated and installed the config.
        XrayConfigApplier().restart()
    if "cliproxyapi" in artifacts:
        # The applier renders again with the key the belt above put in place,
        # writes the YAML with the served fingerprint, and restarts — the same
        # motion the panel's apply runs, so neither path leaves the gateway
        # behind the stored configuration.
        print(CliproxyApiConfigApplier().apply())
    if "overlay" in artifacts:
        for note in switcher.stop(artifacts["overlay"]):
            print(note)
    if "relay" in artifacts:
        change = OverlayRelayApplier(
            controller=process_controller(), agent_port=_agent_port()
        ).apply(artifacts["relay"])
        print(change or "relay unchanged")
    if router_failure:
        raise RuntimeError(router_failure)


def _agent_port() -> int:
    """The agent channel's port, from the panel's settings or the default."""
    try:
        settings = read_config("web/settings.json")
    except (FileNotFoundError, ValueError):
        return WEB_DEFAULT_AGENT_LISTEN_PORT
    return int(settings.get("agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT))


if __name__ == "__main__":
    sys.exit(main())
