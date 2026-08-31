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
import shutil
import ipaddress
import json
import sys

from neutrino_hub.modules.router.constants import (
    ROUTER_DNSMASQ_LINK_PATH,
    ROUTER_DNSMASQ_PATH,
    ROUTER_NFT_PATH,
)
from neutrino_hub.modules.router.dnsmasq_renderer import RouterDnsmasqRenderer
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.routes import (
    RouterDefaultRouteApplier,
    RouterRulesetApplier,
    lookup_xray_uid,
)
from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.constants import GITEA_BINARY_PATH, GITEA_CONF_LINK_PATH
from neutrino_hub.modules.gitea.ops import GiteaConfigApplier, GiteaSecretStore
from neutrino_hub.modules.gitea.renderer import GiteaConfigRenderer
from neutrino_hub.modules.podman import ops as podman_ops
from neutrino_hub.modules.podman.config import PodmanConfig
from neutrino_hub.modules.podman.ops import PodmanRegistriesApplier
from neutrino_hub.modules.podman.renderer import PodmanRegistriesRenderer
from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.constants import (
    SAMBA_CONF_LINK_PATH,
    SAMBA_GENERATED_NAME,
)
from neutrino_hub.modules.samba.ops import SambaConfigApplier, SambaUserManager
from neutrino_hub.modules.samba.renderer import SambaConfigRenderer
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.system.units import SystemdUnitInstaller
from neutrino_hub.utils.json_file import read_config, write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.constants import XRAY_CONFIG_PATH
from neutrino_hub.modules.xray.node_config import XrayNodeList

# --- config ---
DNSMASQ_SERVICE_NAME = "dnsmasq"
COMPONENTS = ("router", "xray", "dnsmasq", "samba", "gitea", "podman")


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
    except (ValueError, FileNotFoundError, CommandError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_artifacts(artifacts)
        return 0

    try:
        _write(artifacts)
        if not args.skip_apply:
            units = SystemdUnitInstaller().install()
            if units:
                print(f"units refreshed: {', '.join(units)}")
            _apply(artifacts)
    except CommandError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"rendered and applied: {', '.join(sorted(artifacts))}")
    return 0


def _render(selected: tuple[str, ...]) -> dict:
    network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
    routing = read_config("xray/routing.json")
    artifacts: dict = {}

    if "xray" in selected:
        node_list = XrayNodeList.from_dict(read_config("xray/nodes.json"))
        artifacts["xray"] = XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
            lan_address=network.primary_lan_address,
        ).render()
    if "router" in selected:
        artifacts["router"] = RouterNftRenderer(
            network=network,
            routing=routing,
            xray_uid=lookup_xray_uid(),
        ).render()
    if "dnsmasq" in selected:
        artifacts["dnsmasq"] = RouterDnsmasqRenderer(
            network=network, routing=routing
        ).render()
    # The optional modules render only where installed: a fresh box without
    # extras still gets a clean full-render run.
    if "samba" in selected and shutil.which("smbd") is None:
        print("samba: not installed, skipping")
    elif "samba" in selected:
        samba_config = SambaConfig.from_dict(read_config("samba/samba.json"))
        samba_config.validate()
        subnets = [
            str(ipaddress.ip_network(interface.lan.cidr, strict=False))
            for interface in network.lan_interfaces
        ]
        artifacts["samba"] = SambaConfigRenderer(
            config=samba_config, lan_subnets=subnets
        ).render()
    if "gitea" in selected:
        if not GITEA_BINARY_PATH.is_file():
            print("gitea: not installed, skipping")
        else:
            gitea_config = GiteaConfig.from_dict(read_config("gitea/gitea.json"))
            gitea_config.validate()
            # Loading mints missing secrets, an effect the render phase
            # normally avoids — but a placeholder here would render an
            # app.ini that must never reach the box, and minting is
            # idempotent, so the lesser evil is to mint.
            artifacts["gitea"] = GiteaConfigRenderer(
                config=gitea_config,
                lan_address=network.primary_lan_address,
                secrets=GiteaSecretStore().load(),
            ).render()
    if "podman" in selected and shutil.which("podman") is None:
        print("podman: not installed, skipping")
    elif "podman" in selected:
        podman_config = PodmanConfig.from_dict(read_config("podman/podman.json"))
        podman_config.validate()
        artifacts["podman"] = podman_ops.container_renderer(podman_config).render()
    return artifacts


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
    if "samba" in artifacts:
        print(f"\n--- {SAMBA_CONF_LINK_PATH} ---")
        print(artifacts["samba"])
    if "gitea" in artifacts:
        print(f"\n--- {GITEA_CONF_LINK_PATH} ---")
        print(artifacts["gitea"])
    if "podman" in artifacts:
        directory = podman_ops.container_applier().directory
        for file_name, text in artifacts["podman"].items():
            print(f"\n--- {directory / file_name} ---")
            print(text)


def _write(artifacts: dict) -> None:
    if "xray" in artifacts:
        # Validates before writing, and must happen even with --skip-apply:
        # the xray unit points at this file, so systemd cannot start the
        # service until it exists.
        XrayConfigApplier().write(artifacts["xray"])
    if "router" in artifacts:
        write_generated(ROUTER_NFT_PATH, artifacts["router"])
    if "dnsmasq" in artifacts:
        write_generated(ROUTER_DNSMASQ_PATH, artifacts["dnsmasq"])
        _link_dnsmasq_config()
    if "samba" in artifacts:
        write_generated(UTILS_GENERATED_DIR / SAMBA_GENERATED_NAME, artifacts["samba"])


def _link_dnsmasq_config() -> None:
    if ROUTER_DNSMASQ_LINK_PATH.is_symlink():
        return
    ROUTER_DNSMASQ_LINK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROUTER_DNSMASQ_LINK_PATH.unlink(missing_ok=True)
    ROUTER_DNSMASQ_LINK_PATH.symlink_to(ROUTER_DNSMASQ_PATH)


def _apply(artifacts: dict) -> None:
    if "xray" in artifacts:
        # _write already validated and installed the config.
        XrayConfigApplier().restart()
    if "router" in artifacts:
        RouterRulesetApplier().apply(artifacts["router"])
        # Rebuilt every time rather than only when the config changes: a next
        # hop whose uplink has since gone away is a black hole, so the route is
        # made to match the uplinks that are live right now.
        network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
        for change in RouterDefaultRouteApplier(network=network).apply():
            print(change)
    if "dnsmasq" in artifacts:
        run(["systemctl", "restart", DNSMASQ_SERVICE_NAME])
    if "samba" in artifacts:
        samba_config = SambaConfig.from_dict(read_config("samba/samba.json"))
        for change in SambaUserManager().converge(samba_config.users):
            print(change)
        print(SambaConfigApplier().apply(artifacts["samba"], config=samba_config))
    if "gitea" in artifacts:
        print(GiteaConfigApplier().apply(artifacts["gitea"]))
    if "podman" in artifacts:
        podman_config = PodmanConfig.from_dict(read_config("podman/podman.json"))
        autostart = [
            container.name
            for container in podman_config.containers
            if container.is_autostart
        ]
        print(
            PodmanRegistriesApplier().apply(
                PodmanRegistriesRenderer(config=podman_config).render()
            )
        )
        print(
            podman_ops.container_applier().apply(
                artifacts["podman"], autostart_names=autostart
            )
        )


if __name__ == "__main__":
    sys.exit(main())
