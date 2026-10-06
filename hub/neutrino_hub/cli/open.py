"""Open the panel in a browser, or the setup wizard before the box is set up.

    nhub open                    # what the Neutrino Hub entry runs
    sudo nhub open --print       # print the address another machine opens
    nhub open --start-service    # the elevated step, run by nhub open itself

Two steps. An elevated step starts the hub's service when it is stopped
and says the address it answers at, with the setup token while the box is
not set up; run without privilege, ``nhub open`` asks for it through UAC,
the administrator prompt of ``osascript`` or ``pkexec``, and only when the
panel does not already answer on loopback. Then the default browser opens
that address as the person, never as root.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


from neutrino_hub.cli.password import is_password_set
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import RouterLinkStatus, device_addresses
from neutrino_hub.platforms.detect import hub_platform, process_controller
from neutrino_hub.system.constants import SYSTEM_SUPERVISED_WEB
from neutrino_hub.utils.constants import is_dev_root_set
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT
from neutrino_hub.web.setup_app import ensure_setup_token

# --- config ---
OPEN_LOOPBACK_HOST = "127.0.0.1"
OPEN_SETTINGS_FILE = "web/settings.json"
OPEN_NETWORK_FILE = "router/network.json"
OPEN_START_SERVICE_FLAG = "--start-service"
OPEN_OUTPUT_FLAG = "--output"
# The route only the panel of a set-up box answers, without a session, and
# how long the entry waits for it.
OPEN_PANEL_PROBE_PATH = "/api/hub/auth/session"
OPEN_PANEL_PROBE_TIMEOUT_S = 2.0


def main() -> int:
    """Open the panel or the wizard, or run one of the two steps alone.

    Returns:
        Process exit status: 0 once the address is opened or printed, 1 when
        the service cannot be started or the person declined to start it, 2
        for the elevated step without privilege.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--print",
        dest="is_print_only",
        action="store_true",
        help="print the address another machine opens instead of opening it",
    )
    action.add_argument(
        OPEN_START_SERVICE_FLAG,
        dest="is_start_service",
        action="store_true",
        help="start the hub's service when it is stopped and print the address",
    )
    parser.add_argument(
        OPEN_OUTPUT_FLAG,
        metavar="PATH",
        default="",
        help=f"with {OPEN_START_SERVICE_FLAG}, write the address here",
    )
    arguments = parser.parse_args()
    platform = hub_platform()

    if arguments.is_start_service:
        if not platform.is_elevated():
            print(
                f"error: {OPEN_START_SERVICE_FLAG} needs {platform.elevation_word}",
                file=sys.stderr,
            )
            return 2
        if not _start_service():
            return 1
        _say(address(OPEN_LOOPBACK_HOST), arguments.output)
        return 0

    if arguments.is_print_only:
        if platform.is_elevated():
            _start_service()
            print(address(_reachable_host()))
            return 0
        print(f"http://{_reachable_host()}:{WEB_DEFAULT_LISTEN_PORT}/")
        print(
            f"run nhub open --print as {platform.elevation_word} for the "
            "setup token",
            file=sys.stderr,
        )
        return 0

    port = _configured_port()
    if platform.is_elevated():
        _start_service()
        url = address(OPEN_LOOPBACK_HOST)
    elif _is_panel_answering(port):
        url = f"http://{OPEN_LOOPBACK_HOST}:{port}/"
    else:
        url = _address_from_elevated_step(platform)
    if not url:
        print(
            f"error: the hub's service was not started; run nhub open as "
            f"{platform.elevation_word} to start it",
            file=sys.stderr,
        )
        return 1
    if not platform.open_browser(url):
        print(url)
    return 0


def address(host: str) -> str:
    """Where the service answers, with the setup token while the box is not set up.

    Args:
        host: The address a browser reaches this machine at.

    Returns:
        ``http://<host>:<http port>/``, and ``?token=`` the setup token
        before setup.

    Raises:
        OSError: When the setup token can be neither read nor made.
    """
    url = f"http://{host}:{_configured_port()}/"
    if is_password_set():
        return url
    return f"{url}?token={ensure_setup_token()}"


def _is_panel_answering(port: int) -> bool:
    """Whether the panel of a set-up box answers on loopback.

    The service serving the setup wizard does not answer the panel's session
    route, so a box that is not set up reads False, and its address with the
    setup token comes from the elevated step.

    Args:
        port: The panel's HTTP port.

    Returns:
        True when the session route answers 200 with the panel's session
        document.
    """
    url = f"http://{OPEN_LOOPBACK_HOST}:{port}{OPEN_PANEL_PROBE_PATH}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=OPEN_PANEL_PROBE_TIMEOUT_S) as answer:
            document = json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(document, dict) and "is_authenticated" in document


def _start_service() -> bool:
    """Start the hub's service when it is not running.

    Returns:
        False when the service manager refused; a development root runs no
        service and is True.
    """
    if is_dev_root_set():
        return True
    controller = process_controller()
    try:
        if not controller.status(SYSTEM_SUPERVISED_WEB).is_active:
            controller.control(SYSTEM_SUPERVISED_WEB, "start")
    except (subprocess.SubprocessError, OSError, KeyError) as error:
        print(f"error: the hub's service did not start ({error})", file=sys.stderr)
        return False
    return True


def _address_from_elevated_step(platform) -> str:
    """Run the elevated step and read back the address it wrote.

    Args:
        platform: This system's :class:`HubPlatform`.

    Returns:
        The address, empty when the step did not run.
    """
    descriptor, name = tempfile.mkstemp(prefix="nhub_open_")
    os.close(descriptor)
    path = Path(name)
    try:
        if not platform.run_elevated(
            ["open", OPEN_START_SERVICE_FLAG, OPEN_OUTPUT_FLAG, str(path)]
        ):
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    finally:
        path.unlink(missing_ok=True)


def _say(url: str, output: str) -> None:
    """Write the address to the file asked for, else to standard output.

    Args:
        url: The address.
        output: The file, empty for standard output.

    Raises:
        OSError: When the file cannot be written.
    """
    if not output:
        print(url)
        return
    Path(output).write_text(url + "\n", encoding="utf-8")


def _configured_port() -> int:
    """The panel's HTTP port, from the settings or the default."""
    try:
        return int(
            read_config(OPEN_SETTINGS_FILE).get("listen_port", WEB_DEFAULT_LISTEN_PORT)
        )
    except (OSError, ValueError, TypeError):
        return WEB_DEFAULT_LISTEN_PORT


def _reachable_host() -> str:
    """The address a browser on another machine reaches this one at.

    The box's addresses are read as everything else of the hub reads them,
    by :func:`device_addresses`, which leaves out loopback, the proxy's TUN
    and the desktop client's files adapter.

    Returns:
        The address of an interface this box answers on, as
        :meth:`RouterNetworkConfig.exposed_device_names_on` reads them; else
        of an interface holding a default route; else the first address the
        box holds; else the hostname.
    """
    addresses = device_addresses()
    try:
        network = RouterNetworkConfig.from_dict(read_config(OPEN_NETWORK_FILE))
    except (FileNotFoundError, ValueError):
        network = RouterNetworkConfig.from_dict({})
    status = RouterLinkStatus()
    routed = [name for name in addresses if status.gateway_for(name) is not None]
    for name in [*network.exposed_device_names_on(list(addresses)), *routed]:
        if addresses.get(name):
            return addresses[name].partition("/")[0]
    for held in addresses.values():
        return held.partition("/")[0]
    return socket.gethostname()
