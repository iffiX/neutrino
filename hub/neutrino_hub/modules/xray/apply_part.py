"""The proxy core as one component of an apply, given through the edition table.

``nhub apply`` and the panel's converge step render xray's configuration
from ``config/xray/``, write it, and restart xray through this one class.
"""

import json

from neutrino_hub.modules.tun.ops import egress_interface
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.config_renderer import XrayConfigRenderer
from neutrino_hub.modules.xray.constants import (
    XRAY_CONFIG_PATH,
    XRAY_NODES_FILE,
    XRAY_SUPERVISED_NAME,
)
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_health import XrayNodeHealthStore
from neutrino_hub.modules.xray.node_secrets import resolve_node_secrets
from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.utils.json_file import read_config


def _stored_down_tags() -> set[str]:
    """The outbound tags whose newest stored measurement failed."""
    store = XrayNodeHealthStore()
    store.load()
    return {tag for tag, health in store.health().items() if health.is_down}


class XrayApplyComponent:
    """Render, print, write and restart the proxy core.

    Attributes:
        name: The component's name on ``nhub apply --only``.
    """

    name = XRAY_SUPERVISED_NAME

    def render(
        self,
        *,
        routing: dict,
        network_resolvers: list,
        node_list: "XrayNodeList | None" = None,
        down_tags: "set | None" = None,
    ) -> dict:
        """Render xray's configuration.

        Args:
            routing: The routing options as they will be rendered.
            network_resolvers: The network's resolvers, as read for this
                apply.
            node_list: The nodes; None reads ``config/xray/nodes.json``.
            down_tags: The outbounds measured down; None reads the stored
                measurements.

        Returns:
            The configuration, every node's secret resolved.

        Raises:
            FileNotFoundError: When the box is not set up.
            ValueError: When a file is not valid JSON.
        """
        if node_list is None:
            node_list = XrayNodeList.from_dict(read_config(XRAY_NODES_FILE))
        resolve_node_secrets(node_list)
        return XrayConfigRenderer(
            node_list=node_list,
            routing=routing,
            down_tags=down_tags if down_tags is not None else _stored_down_tags(),
            is_transparent=is_linux(),
            egress_interface=egress_interface(routing),
            network_resolvers=network_resolvers,
        ).render()

    def describe(self, artifact: dict) -> str:
        """What a dry run prints for the rendered configuration.

        Args:
            artifact: What :meth:`render` returned.

        Returns:
            The file's path as a heading, then its text.
        """
        return f"--- {XRAY_CONFIG_PATH} ---\n{json.dumps(artifact, indent=2)}"

    def write(self, artifact: dict) -> None:
        """Validate and write the configuration, restarting nothing.

        Args:
            artifact: What :meth:`render` returned.

        Raises:
            RuntimeError: When xray refuses it.
            OSError: When it cannot be written.
        """
        XrayConfigApplier().write(artifact)

    def restart(self) -> None:
        """Restart xray on what :meth:`write` installed.

        Raises:
            RuntimeError: When xray does not come up.
            subprocess.SubprocessError: When the restart fails.
        """
        XrayConfigApplier().restart()

    def apply_if_changed(self, artifact: dict) -> bool:
        """Install and restart only when the configuration changed.

        Args:
            artifact: What :meth:`render` returned.

        Returns:
            True when xray was restarted.

        Raises:
            RuntimeError: When xray refuses it.
            OSError: When it cannot be written.
            subprocess.SubprocessError: When the restart fails.
        """
        return XrayConfigApplier().apply_if_changed(artifact)
