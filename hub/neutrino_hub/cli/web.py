"""Run the control panel.

    sudo nhub serve               # listen on the configured port
    sudo nhub serve --reload      # development, auto-restart

The panel binds every interface, and the nftables input chain is what keeps it
reachable only from the LAN and the overlay. Both halves matter: dropping the
firewall rule without changing this would expose it upstream.
"""

import argparse
import sys

import uvicorn

from neutrino_hub.utils.json_file import read_config

# --- config ---
DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 8080
APPLICATION_PATH = "neutrino_hub.web.app:create_app"


def main() -> int:
    """Start the panel.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_LISTEN_HOST, help="address to bind")
    parser.add_argument(
        "--port", type=int, default=None, help="port to bind (default: from config)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="restart on source changes"
    )
    args = parser.parse_args()

    port = args.port if args.port is not None else _configured_port()
    uvicorn.run(
        APPLICATION_PATH,
        factory=True,
        host=args.host,
        port=port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def _configured_port() -> int:
    try:
        return read_config("web/settings.json").get("listen_port", DEFAULT_LISTEN_PORT)
    except (FileNotFoundError, ValueError):
        return DEFAULT_LISTEN_PORT


if __name__ == "__main__":
    sys.exit(main())
