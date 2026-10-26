"""Rendering what the transport opens: ``generated/transport.json``.

Pure: the settings come in, the document goes out, and nothing here reads a
file or starts a process (architecture.md, "render, validate, apply").
"""

from neutrino_hub.modules.channel.constants import CHANNEL_LEGACY_TLS_PORT
from neutrino_hub.modules.frp.constants import FRP_LOOPBACK_PORTS
from neutrino_hub.modules.transport.constants import TRANSPORT_LISTENER_MAIN


class TransportConfigRenderer:
    """Composes the transport's configuration from the hub's settings."""

    def __init__(
        self,
        *,
        listen_port: int,
        control_socket: str,
        is_legacy_enabled: bool,
        frp_ports: "dict | None" = None,
    ):
        """
        Args:
            listen_port: The agent port.
            control_socket: The local channel's listener the transport opens.
            is_legacy_enabled: Whether the transport hands a TLS first byte
                to the legacy listener.
            frp_ports: Vendor to its loopback port; None is the two vendors'.
        """
        self._listen_port = int(listen_port)
        self._control_socket = control_socket
        self._is_legacy_enabled = bool(is_legacy_enabled)
        self._frp_ports = dict(FRP_LOOPBACK_PORTS if frp_ports is None else frp_ports)

    def render(self) -> dict:
        """The document the transport reads at its start.

        Returns:
            ``{listen_port, frp_listeners, legacy_tls_port, control_socket}``,
            ``frp_listeners`` one ``{port, listener}`` per vendor and
            ``legacy_tls_port`` 0 while the legacy listener is off.
        """
        return {
            "listen_port": self._listen_port,
            "frp_listeners": [
                {"port": int(port), "listener": vendor}
                for vendor, port in self._frp_ports.items()
                if vendor != TRANSPORT_LISTENER_MAIN
            ],
            "legacy_tls_port": (
                CHANNEL_LEGACY_TLS_PORT if self._is_legacy_enabled else 0
            ),
            "control_socket": self._control_socket,
        }
