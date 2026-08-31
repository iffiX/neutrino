"""Run the hub in the foreground.

    sudo nhub run                     # the panel, the proxy core, the AI gateway
    sudo nhub run --only-web          # one of them; this is what each unit starts
    sudo nhub run --only-xray
    sudo nhub run --only-cliproxyapi
    sudo nhub run --only-dnsmasq
    sudo nhub --dev run               # all of them, plus the frontend dev server

The ``--only`` forms are what the units name, so systemd keeps deciding
who each daemon runs as and what it may reach for — the proxy core in
particular is unprivileged with two capabilities, which a parent process
cannot hand a child without re-implementing what the unit already declares.

With no ``--only`` this supervises all three itself, for a machine that has no
units: a working copy under ``--dev``, or anyone who would rather watch them
run than read journalctl.
"""

import argparse
import os
import pwd
import shutil
import signal
import subprocess
import sys

import uvicorn

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_DIR,
    CLIPROXYAPI_GENERATED_NAME,
)
from neutrino_hub.modules.router.constants import ROUTER_DNSMASQ_PATH
from neutrino_hub.modules.xray.constants import (
    XRAY_ASSET_DIR,
    XRAY_ASSET_ENV,
    XRAY_BINARY,
    XRAY_CONFIG_PATH,
)
from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_GENERATED_DIR,
    is_dev_root_set,
)
from neutrino_hub.web.constants import WEB_DEFAULT_LISTEN_PORT
from neutrino_hub.utils.json_file import read_config

# --- config ---
DEFAULT_LISTEN_HOST = "0.0.0.0"
APPLICATION_PATH = "neutrino_hub.web.app:create_app"
PANEL_SETTINGS_FILE = "web/settings.json"
# Where the frontend's dev server is started from, relative to the checkout.
FRONTEND_DIR_NAME = "hub/frontend"
FRONTEND_COMMAND = ("npm", "run", "dev")
# How long a child gets to stop before it is killed.
CHILD_STOP_TIMEOUT_S = 10
# Where dnsmasq is, in the order the families put it. Debian and Fedora say
# sbin, Arch says bin, and PATH under a unit is neither reliably.
DNSMASQ_BINARIES = ("/usr/sbin/dnsmasq", "/usr/bin/dnsmasq")
# The account dnsmasq drops to once it holds its sockets. Every family's
# package creates it; a machine that somehow has not gets dnsmasq's built-in
# default instead of a startup failure.
DNSMASQ_USER = "dnsmasq"


def main() -> int:
    """Start what was asked for.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=DEFAULT_LISTEN_HOST, help="address to bind")
    parser.add_argument(
        "--port", type=int, default=None, help="port to bind (default: from config)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="restart the panel on source changes"
    )
    group = parser.add_mutually_exclusive_group()
    for name in ("web", "xray", "cliproxyapi", "dnsmasq"):
        group.add_argument(
            f"--only-{name}",
            dest="only",
            action="store_const",
            const=name,
            help=f"run only the {name} process, as its unit does",
        )
    arguments = parser.parse_args()

    if arguments.only == "xray":
        return _exec_xray()
    if arguments.only == "cliproxyapi":
        return _exec_cliproxyapi()
    if arguments.only == "dnsmasq":
        return _exec_dnsmasq()
    if not _is_set_up():
        print(
            f"error: nothing is configured under {UTILS_CONFIG_DIR}; "
            f"run {'nhub --dev setup' if is_dev_root_set() else 'sudo nhub setup'}",
            file=sys.stderr,
        )
        return 1
    if arguments.only == "web":
        return _serve_panel(arguments)
    return _supervise(arguments)


def _is_set_up() -> bool:
    """Whether there is a configuration to run against.

    Returns:
        True when the panel's own settings are there, which is the last thing
        setup writes.
    """
    return (UTILS_CONFIG_DIR / PANEL_SETTINGS_FILE).is_file()


def _exec_xray() -> int:
    """Become the proxy core.

    Replaces this process rather than forking one, so the unit's account and
    capabilities carry straight into the binary and nothing lingers between
    systemd and the daemon it is watching.

    Returns:
        Never; the process is replaced.
    """
    os.environ[XRAY_ASSET_ENV] = XRAY_ASSET_DIR
    os.execv(XRAY_BINARY, [XRAY_BINARY, "run", "-config", str(XRAY_CONFIG_PATH)])
    return 1


def _exec_cliproxyapi() -> int:
    """Become the AI gateway.

    Returns:
        Never; the process is replaced.
    """
    binary = str(CLIPROXYAPI_BINARY_PATH)
    config = str(UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME)
    CLIPROXYAPI_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(CLIPROXYAPI_DIR)
    os.execv(binary, [binary, "--config", config])
    return 1


def _exec_dnsmasq() -> int:
    """Become the LAN's name service.

    The generated file is named outright and no configuration directory is
    read, so what dnsmasq runs on is what the hub rendered and nothing a
    distribution left in /etc/dnsmasq.conf beside it.

    Returns:
        Never; the process is replaced. 1 when dnsmasq is not installed.
    """
    binary = next((path for path in DNSMASQ_BINARIES if os.path.isfile(path)), None)
    binary = binary or shutil.which("dnsmasq")
    if binary is None:
        print("error: dnsmasq is not installed", file=sys.stderr)
        return 1
    arguments = [
        binary,
        # Foreground, so systemd watches dnsmasq itself rather than a fork,
        # and no pid file has to exist anywhere for it to start.
        "--keep-in-foreground",
        "--pid-file=",
        f"--conf-file={ROUTER_DNSMASQ_PATH}",
    ]
    try:
        pwd.getpwnam(DNSMASQ_USER)
    except KeyError:
        pass
    else:
        arguments.append(f"--user={DNSMASQ_USER}")
    os.execv(binary, arguments)
    return 1


def _serve_panel(arguments) -> int:
    """Run the control panel, and nothing else.

    Args:
        arguments: The parsed command line.

    Returns:
        Process exit status.
    """
    port = arguments.port if arguments.port is not None else _configured_port()
    uvicorn.run(
        APPLICATION_PATH,
        factory=True,
        host=arguments.host,
        port=port,
        reload=arguments.reload,
        log_level="info",
    )
    return 0


def _supervise(arguments) -> int:
    """Run every process this machine needs, and stop them together.

    Args:
        arguments: The parsed command line.

    Returns:
        Process exit status.
    """
    children = []
    for name in ("xray", "cliproxyapi"):
        started = _start_child(name)
        if started is not None:
            children.append(started)
    if is_dev_root_set():
        frontend = _start_frontend()
        if frontend is not None:
            children.append(frontend)

    try:
        return _serve_panel(arguments)
    finally:
        _stop(children)


def _start_child(name: str):
    """Start one daemon as a child of this process.

    Args:
        name: ``xray`` or ``cliproxyapi``.

    Returns:
        The process, or None when its binary is not installed.
    """
    binary = XRAY_BINARY if name == "xray" else str(CLIPROXYAPI_BINARY_PATH)
    if not os.path.isfile(binary):
        print(f"  {name}: {binary} is not there, so it is not started")
        return None
    print(f"  {name}: starting")
    return subprocess.Popen(
        [sys.executable, "-m", "neutrino_hub.cli.entry", "run", f"--only-{name}"]
    )


def _start_frontend():
    """Start the frontend's dev server beside the panel.

    Returns:
        The process, or None where node is not installed.
    """
    from neutrino_hub.cli.dev_root import checkout_root

    directory = checkout_root() / FRONTEND_DIR_NAME
    try:
        process = subprocess.Popen(FRONTEND_COMMAND, cwd=directory)
    except (OSError, FileNotFoundError):
        print("  frontend: npm is not installed, so the built panel is served")
        return None
    print("  frontend: npm run dev")
    return process


def _stop(children: list) -> None:
    """Stop every child, and wait for it.

    Args:
        children: What :func:`_start_child` returned.
    """
    for child in children:
        child.send_signal(signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=CHILD_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            child.kill()


def _configured_port() -> int:
    """The port the panel listens on, from the settings or the default."""
    try:
        return read_config("web/settings.json").get(
            "listen_port", WEB_DEFAULT_LISTEN_PORT
        )
    except (FileNotFoundError, ValueError):
        return WEB_DEFAULT_LISTEN_PORT


if __name__ == "__main__":
    sys.exit(main())
