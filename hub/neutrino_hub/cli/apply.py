"""Render every generated config from ``config/``, validate it, and apply it.

This is the command-line half of the pipeline the web panel drives. Run it after
editing anything under ``config/`` by hand:

    sudo nhub apply               # render, validate, apply all
    nhub apply --dry-run          # render and print, no effects
    sudo nhub apply --only router

The unit files come with it. They ship in the package rather than being
rendered from ``config/``, so an upgrade that changes one lands here: writing
them is part of making the box true, and a unit already current is left
alone.
"""

import argparse
import json
import subprocess
import sys
from socket import gethostname

from neutrino_hub.modules.easytier.constants import EASYTIER_GENERATED_NAME
from neutrino_hub.modules.easytier.ops import EasyTierConfigApplier
from neutrino_hub.modules.easytier.ops import read_stored as read_easytier
from neutrino_hub.modules.easytier.renderer import render_config as render_easytier
from neutrino_hub.modules.netbird.ops import NetbirdInboundGate
from neutrino_hub.modules.router.constants import (
    ROUTER_DNSMASQ_PATH,
    ROUTER_NFT_PATH,
    ROUTER_OVERLAY_NETBIRD,
)
from neutrino_hub.modules.router.dnsmasq_renderer import RouterDnsmasqRenderer
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.routes import (
    RouterInterfaceApplier,
    RouterRulesetApplier,
    lookup_xray_uid,
)
from neutrino_hub.modules.router.supplicant import (
    write_config as write_supplicant_config,
)
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.system.constants import SYSTEM_CORE_UNITS
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
)
from neutrino_hub.utils.subprocess_run import command_failure_text, run
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.constants import XRAY_CONFIG_PATH
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets

# --- config ---
DNSMASQ_SERVICE_NAME = SYSTEM_CORE_UNITS["dnsmasq"]
COMPONENTS = ("router", "xray", "dnsmasq", "cliproxyapi", "easytier")


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
        _write(artifacts)
        if not args.skip_apply:
            units = SystemdUnitInstaller().install()
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

    if "xray" in selected:
        node_list = XrayNodeList.from_dict(read_config("xray/nodes.json"))
        resolve_node_secrets(node_list)
        artifacts["xray"] = XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
        ).render()
    if "router" in selected:
        artifacts["router"] = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
            agent_port=_agent_port(),
        ).render()
    if "dnsmasq" in selected:
        artifacts["dnsmasq"] = RouterDnsmasqRenderer(
            network=network, routing=routing
        ).render()
    if "cliproxyapi" in selected:
        gateway = CliproxyApiConfigApplier()
        if not gateway.is_installed:
            print("cliproxyapi: not installed, skipping")
        else:
            artifacts["cliproxyapi"] = gateway.render_with_stored_key()
    if "easytier" in selected:
        overlay = read_easytier()
        if not overlay.is_configured:
            print("easytier: no network configured, skipping")
        else:
            artifacts["easytier"] = overlay
    return artifacts


def _agent_port() -> int:
    """The agent channel's port, from the panel settings or the default."""
    try:
        return int(
            read_config("web/settings.json").get(
                "agent_listen_port", WEB_DEFAULT_AGENT_LISTEN_PORT
            )
        )
    except (FileNotFoundError, ValueError):
        return WEB_DEFAULT_AGENT_LISTEN_PORT


def _print_artifacts(artifacts: dict) -> None:
    if "xray" in artifacts:
        print(f"--- {XRAY_CONFIG_PATH} ---")
        print(json.dumps(artifacts["xray"], indent=2))
    if "router" in artifacts:
        print(f"\n--- {ROUTER_NFT_PATH} ---")
        print(artifacts["router"])
    if "dnsmasq" in artifacts:
        print(f"\n--- {ROUTER_DNSMASQ_PATH} ---")
        print(artifacts["dnsmasq"])
    if "cliproxyapi" in artifacts:
        print(f"\n--- {UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME} ---")
        print(artifacts["cliproxyapi"])
    if "easytier" in artifacts:
        # The rendered file carries the network secret, which is the key the
        # whole network is encrypted under. A dry run prints what a person
        # asked to see, not that.
        print(f"\n--- {UTILS_GENERATED_DIR / EASYTIER_GENERATED_NAME} ---")
        print(
            render_easytier(
                artifacts["easytier"], secret="<network secret>", hostname=gethostname()
            )
        )


def _write(artifacts: dict) -> None:
    if "xray" in artifacts:
        # Validates before writing, and must happen even with --skip-apply:
        # the xray unit points at this file, so systemd cannot start the
        # service until it exists.
        XrayConfigApplier().write(artifacts["xray"])
    if "dnsmasq" in artifacts:
        write_generated(ROUTER_DNSMASQ_PATH, artifacts["dnsmasq"])


def _apply(artifacts: dict) -> None:
    if "xray" in artifacts:
        # _write already validated and installed the config.
        XrayConfigApplier().restart()
    if "router" in artifacts:
        network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
        RouterRulesetApplier().apply(
            artifacts["router"],
            is_forwarding=bool(network.lan_interfaces or network.wan_interfaces),
        )
        # Written after the load, never before: the panel reads this file to
        # say where traffic is going, and a ruleset that only reached the disk
        # is where traffic was about to go.
        write_generated(ROUTER_NFT_PATH, artifacts["router"])
        # Rebuilt every time rather than only when the config changes: an
        # address the hub set does not survive a reboot by itself, and a next
        # hop whose uplink has since gone away is a black hole. Applying the
        # whole thing is what brings the box back as configured — this runs
        # from `neutrino_hub_router.service`, before anything it serves.
        for change in RouterInterfaceApplier(network=network).apply_all():
            print(change)
        # An overlay's own daemon puts an accept for its interface back into
        # this chain seconds after any reload, so the exposure switch has to
        # reach it too or a closed overlay is only closed on paper.
        for overlay in network.overlays:
            if overlay.provider != ROUTER_OVERLAY_NETBIRD:
                continue
            note = NetbirdInboundGate().converge(is_blocked=not overlay.is_exposed)
            if note:
                print(f"{overlay.title}: {note}")
    if "dnsmasq" in artifacts:
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])
    if "cliproxyapi" in artifacts:
        # The applier renders again with the key the belt above put in place,
        # writes the YAML with the served fingerprint, and restarts — the same
        # motion the panel's apply runs, so neither path leaves the gateway
        # behind the stored configuration.
        print(CliproxyApiConfigApplier().apply())
    if "easytier" in artifacts:
        print(
            EasyTierConfigApplier().apply(artifacts["easytier"], hostname=gethostname())
        )


if __name__ == "__main__":
    sys.exit(main())
