"""First run: everything the gateway needs, in one command.

    sudo nhub setup
    printf '%s' "$PANEL_PASSWORD" | sudo nhub setup --password-stdin

Runs once. A box that already has a panel password is a box somebody
configured, and this refuses rather than landing on top of it; `nhub reset all`
returns one to a fresh state and `nhub apply` makes a config change true.

Every step checks the system before it acts, so a run that failed halfway
converges rather than duplicating work.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
import zipfile
from functools import partial
from pathlib import Path

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.routes import RouterInterfaceApplier
from neutrino_hub.system.constants import (
    SYSTEM_CHECKOUT_PACKAGES,
    SYSTEM_RUNTIME_PACKAGES,
    SYSTEM_FAIL2BAN_JAIL,
    SYSTEM_FAIL2BAN_JAIL_PATH,
    SYSTEM_XRAY_USER,
)
from neutrino_hub.modules.samba.constants import SAMBA_DEFAULT_SHARE_DIR
from neutrino_hub.modules.cliproxyapi.provisioner import CliproxyApiProvisioner
from neutrino_hub.system.machine import machine_architecture, require_architecture
from neutrino_hub.modules.registry import MODULE_SPECS
from neutrino_hub.system.provisioning import plan_for
from neutrino_hub.system.installation import (
    is_packaged,
    project_root,
    venv_python,
)
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.system.units import SystemdUnitInstaller
from neutrino_hub.utils.constants import (
    is_dev_root_set,
    UTILS_CONFIG_DIR,
    UTILS_EXAMPLES_DIR,
    UTILS_GEODATA_DIR,
    UTILS_GENERATED_DIR,
    UTILS_LOG_DIR,
    UTILS_PACKAGE_ROOT,
)
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.system import package_manager
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.constants import (
    XRAY_ASSET_ARCHITECTURES,
    XRAY_BINARY,
    XRAY_BINARY_NAME,
    XRAY_DOWNLOAD_URL,
    XRAY_GEODATA,
    XRAY_SHA256,
    XRAY_SUPPORTED_ARCHITECTURES,
    XRAY_VERSION,
)

from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.web.constants import (
    WEB_DEFAULT_LISTEN_PORT,
    WEB_SETUP_GRACE_S,
    WEB_SETUP_WAIT_S,
)
from neutrino_hub.web.setup_app import WebSetupServer, WebSetupSession

from neutrino_hub.cli.password import is_password_set, store_password
from neutrino_hub.cli.reporter import InstallReporter, InstallSessionReporter
from neutrino_hub.cli import wizard

# --- config ---
# What the panel is asked for, on loopback, once it is running.
SETUP_LOGIN_PATH = "/api/auth/login"
SETUP_ENROLLMENT_PATH = "/api/devices/enrollment"
SETUP_PANEL_TIMEOUT_S = 10
# How long the panel gets to start listening before its link is given up on.
SETUP_PANEL_WAIT_S = 30.0
SETUP_PANEL_POLL_S = 1.0
# The browser wizard listens on every address, because whoever opens it is on
# one of this machine's networks and setup does not yet know which.
SETUP_BROWSER_HOST = "0.0.0.0"
# What starting the services means. In a browser the panel is left out and
# started last, because until then the wizard is what holds its port.
SETUP_CORE_SERVICES = ("router", "xray", "dnsmasq", "web")
# What opens a page on a machine that has a desktop to open one on. A box
# without it is a box nobody is sitting at, and its setup stays in the
# terminal rather than printing a link nothing will follow.
SETUP_BROWSER_OPENER = "xdg-open"
# Asking for this port is asking the operating system for whichever one is
# free, which is what the wizard falls back to when the panel's is taken.
SETUP_BROWSER_ANY_PORT = 0
SETUP_SERVICES_BEFORE_PANEL = ("router", "xray", "dnsmasq")
CONFIG_FILES = (
    "xray/nodes.json",
    "xray/routing.json",
    "router/network.json",
    "web/settings.json",
    "samba/samba.json",
    "gitea/gitea.json",
    "podman/podman.json",
    "devices/devices.json",
)


def main() -> int:
    """Set the gateway up.

    The step table is defined at the bottom of this file, after the step
    functions it names.

    Returns:
        Process exit status: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--stdin",
        action="store_true",
        help="read every answer, as one JSON object, from standard input",
    )
    source.add_argument(
        "--json",
        metavar="PATH",
        help="read every answer from this JSON file",
    )
    arguments = parser.parse_args()

    if os.geteuid() != 0:
        print("error: setup must run as root (sudo nhub setup)", file=sys.stderr)
        return 1
    if is_password_set():
        print(
            "error: this hub is already set up. `nhub apply` makes a config "
            "change true; `nhub reset all` returns the box to a fresh one.",
            file=sys.stderr,
        )
        return 1
    server = None
    try:
        answers, server = _answers(arguments)
    except wizard.WizardAborted as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    steps = [step for step in CORE_STEPS if step[1] not in _skipped_steps()]
    is_coloured = not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    if server is None:
        reporter = InstallReporter(
            total_step_count=len(steps) + 2, is_color_enabled=is_coloured
        )
    else:
        steps = _panel_started_last(steps)
        reporter = InstallSessionReporter(
            session=server.session,
            total_step_count=len(steps) + 2,
            is_color_enabled=is_coloured,
        )
    return _setup(reporter, steps, answers, server=server)


def _answers(arguments):
    """What this run was told, however it was told.

    Args:
        arguments: The parsed command line.

    Returns:
        The answers to act on, and the server the browser answered on — None
        for every other way of answering, because there is nothing to shut
        down afterwards.

    Raises:
        WizardAborted: On an answers document that cannot be used, or a
            wizard nobody finished.
    """
    if arguments.stdin:
        return wizard.from_document(_parsed(sys.stdin.read(), "standard input")), None
    if arguments.json:
        path = Path(arguments.json)
        try:
            document = _parsed(path.read_text(encoding="utf-8"), str(path))
        except OSError as error:
            raise wizard.WizardAborted(str(error)) from error
        return wizard.from_document(document), None
    answered = _browser_answers()
    if answered is not None:
        return answered
    return wizard.ask(), None


def _browser_answers():
    """Open the questions in a browser, and wait for them to come back.

    Returns:
        The answers and the server they arrived on, or None when there is no
        browser to open or whoever is at the keyboard would rather answer in
        the terminal.

    Raises:
        WizardAborted: When this machine has nothing to configure.
    """
    if shutil.which(SETUP_BROWSER_OPENER) is None:
        # Nothing here can open a page, so a link would be a line nobody
        # follows. The terminal's own screens are the whole wizard.
        wizard.welcome()
        return None
    session = WebSetupSession(context=wizard.context())
    server = _browser_server(session)
    if server is None:
        wizard.welcome()
        return None
    _open_browser(f"http://127.0.0.1:{server.port}/?token={session.token}")
    while True:
        is_answered = wizard.offer_browser(
            urls=_reachable_urls(server.port),
            token=session.token,
            arrived=lambda: bool(session.wait(WEB_SETUP_WAIT_S)),
        )
        if not is_answered:
            server.stop()
            return None
        try:
            return wizard.from_document(session.wait(WEB_SETUP_WAIT_S)), server
        except wizard.WizardAborted as error:
            # The browser is the one that can fix this, so it is told — and so
            # is the terminal, which is where a run that goes wrong is read.
            print(f"\n  the browser sent answers that cannot be used: {error}")
            session.reject(str(error))


def _open_browser(url: str) -> None:
    """Open the wizard on this machine, and carry on either way.

    Args:
        url: What to open, on loopback because the browser being opened is
            this machine's own.
    """
    try:
        run([SETUP_BROWSER_OPENER, url], is_checked=False, timeout_s=5)
    except (CommandError, OSError):
        # The link is on the screen either way; an opener that refuses is not
        # a reason to stop.
        pass


def _browser_server(session):
    """The wizard's server, on the best port it can get.

    The panel's own port first, and for its reasons: it is the one the
    firewall opens to the served networks, and the one whoever set this box up
    will have in their address bar afterwards. Anything already holding it
    means taking whichever port is free instead — a wizard on an odd port is
    still a wizard, and the terminal prints the address either way.

    Args:
        session: The run to serve.

    Returns:
        A server that is listening, or None when nothing could be started at
        all — which is not a failure, only the terminal doing the asking.
    """
    for wanted in (_browser_port(), SETUP_BROWSER_ANY_PORT):
        try:
            server = WebSetupServer(
                session=session, host=SETUP_BROWSER_HOST, port=wanted
            )
            if server.start():
                return server
        except (OSError, RuntimeError, ValueError) as error:
            print(f"\n  the browser wizard could not start: {error}", file=sys.stderr)
            return None
    print(
        "\n  no port could be found for the browser wizard.",
        file=sys.stderr,
    )
    return None


def _browser_port() -> int:
    """What the browser wizard asks for first.

    Returns:
        The panel's own port.
    """
    try:
        return _configured_port()
    except (FileNotFoundError, ValueError):
        return WEB_DEFAULT_LISTEN_PORT


def _reachable_urls(port: int) -> list:
    """Every address this machine can be opened at right now.

    Before setup there is no configuration to read a served address out of,
    so this is what the interfaces actually carry — and all of them, because
    which one the browser is on is not this machine's to know.

    Args:
        port: The port the wizard actually took.

    Returns:
        One URL per address, the hostname when no interface carries one.
    """
    urls = []
    for link in RouterLinkStatus().all_links():
        if link.name == "lo" or not link.ipv4_address:
            continue
        urls.append(f"http://{link.ipv4_address.split('/')[0]}:{port}")
    return urls or [f"http://{socket.gethostname()}:{port}"]


def _panel_started_last(steps: list) -> list:
    """The step table with the panel left out of starting the services.

    The browser wizard is holding the panel's port, so starting the panel
    among the others would fail to bind. It is started at the very end
    instead, once the wizard has let go.

    Args:
        steps: The table to rewrite.

    Returns:
        The same table, with the starting step narrowed.
    """
    return [
        (
            (
                description,
                partial(_step_start_services, names=SETUP_SERVICES_BEFORE_PANEL),
            )
            if step is _step_start_services
            else (description, step)
        )
        for description, step in steps
    ]


def _parsed(text: str, what: str) -> dict:
    """One JSON document, or a refusal naming where it came from.

    Args:
        text: The document.
        what: Where it was read from, for the message.

    Returns:
        The parsed object.

    Raises:
        WizardAborted: When it is not valid JSON.
    """
    try:
        return json.loads(text)
    except ValueError as error:
        raise wizard.WizardAborted(f"{what} is not valid JSON: {error}") from error


def _skipped_steps() -> tuple:
    """The steps a development root does not run.

    A checkout takes the interfaces over and writes the firewall exactly as a
    package does, because those are what it exists to develop. The one thing
    it does not do is install the hub as a service: `nhub --dev run` is what
    runs the panel instead. The table is in design/install_and_dev.md.

    Returns:
        The step functions to leave out, empty on a real install.
    """
    if not is_dev_root_set():
        return ()
    return (_step_systemd_units, _step_enable_services, _step_start_services)


def _setup(reporter: InstallReporter, steps: list, answers, *, server=None) -> int:
    """Run every step, then store the password and hand the box over.

    Args:
        reporter: Where progress lines go.
        steps: The step table to run, in order.
        answers: What the wizard collected.
        server: The browser wizard's server when the questions were answered
            there, which has to give the panel's port back before the panel
            can start. None when they were answered anywhere else.

    Returns:
        Process exit status.
    """
    reporter.banner("Neutrino Hub setup")
    for description, step in steps:
        reporter.start(description)
        try:
            note, is_changed = step(reporter)
        except (CommandError, OSError, ValueError) as error:
            reporter.failed(str(error))
            return 1
        if is_changed:
            reporter.done(note)
        else:
            reporter.skipped(note)
        if step is _step_config_files:
            # After the examples land and before anything applies them: what
            # the wizard planned replaces the three-port appliance and the
            # placeholder nodes they describe. Guarded like a step, because
            # it fails the same ways and a traceback here says nothing.
            reporter.start("Writing what you chose")
            try:
                write_config("router/network.json", answers.network.to_dict())
                _write_proxy(answers.proxy)
                _write_listen_port(answers.listen_port)
            except (CommandError, OSError, ValueError, TypeError) as error:
                reporter.failed(str(error))
                return 1
            reporter.done("network, proxy and panel port")

    for name in answers.services:
        reporter.start(f"Installing {name}")
        try:
            note = _install_service(name, reporter)
        except (CommandError, OSError, ValueError, RuntimeError) as error:
            # One optional module refusing is not a failed setup: the gateway
            # is already a gateway, and the Services page can try again.
            reporter.skipped(f"not installed: {error}")
            continue
        reporter.done(note)

    # Last, because the settings file it writes into is one of the files the
    # steps above copy from its example.
    reporter.start("Setting the panel password")
    store_password(answers.password)
    reporter.done("stored")

    panel_url = _panel_url()
    if server is not None:
        return _hand_over(server, panel_url)
    _start_panel()
    link, note = _enrollment_link(answers.password)
    wizard.finish(panel_url=panel_url, link=link, note=note, joined=_joined_devices)
    return 0


def _hand_over(server, panel_url: str) -> int:
    """Give the port back and start the panel the browser goes on to.

    The enrollment link is not minted here: a browser that has the panel has
    the Devices page, which is where links come from. The terminal is given
    one only because it has nothing else.

    Args:
        server: The browser wizard's server.
        panel_url: Where the panel will answer.

    Returns:
        Process exit status.
    """
    server.session.finish(panel_url=panel_url)
    # Long enough for one more poll to read that last state before the
    # connection it reads over goes away.
    time.sleep(WEB_SETUP_GRACE_S)
    server.stop()
    _start_panel()
    print()
    print(f"  The panel is at   {panel_url}")
    print()
    return 0


def _start_panel() -> None:
    """Start the panel, where starting it is this command's job.

    A development root installs no units — `nhub --dev run` is what runs the
    panel there — so asking systemd for one is asking for a unit nobody
    wrote.
    """
    if is_dev_root_set():
        return
    SystemdServiceController().control("web", "restart")


def _joined_devices() -> list:
    """The devices that have enrolled, as the panel wrote them down.

    Returns:
        Their names, empty when none has joined or nothing was written.
    """
    try:
        devices = read_config("devices/devices.json").get("devices", {})
    except (FileNotFoundError, ValueError):
        return []
    return [
        record.get("name") or address
        for address, record in devices.items()
        if isinstance(record, dict)
    ]


def _install_service(name: str, reporter: InstallReporter) -> str:
    """Install one optional module, as the panel's Services page would.

    Consent was given on the wizard's own screen, which is why it is passed
    rather than asked for again here.

    Args:
        name: The module's registry name.
        reporter: Where the provisioner's progress lines go.

    Returns:
        What the provisioner reported doing.
    """
    spec = MODULE_SPECS[name]
    provisioner = spec.provisioner()
    if plan_for(provisioner).is_consent_needed:
        result = provisioner.provision(is_consented=True, report=reporter.note)
    else:
        result = provisioner.provision(report=reporter.note)
    run(["systemctl", "enable", "--now", spec.unit], is_checked=False)
    return result.message


def _write_listen_port(port: int) -> None:
    """Put the panel on the port that was asked for.

    Args:
        port: What the wizard collected.
    """
    settings = read_config("web/settings.json")
    settings["listen_port"] = port
    write_config("web/settings.json", settings)


def _write_proxy(proxy) -> None:
    """Put the proxy screen's answers into `config/xray/`.

    Args:
        proxy: What the wizard collected.
    """
    # Read and replace rather than build: the list carries a balancer strategy
    # and probe settings that are the example's to state, not the wizard's.
    nodes = XrayNodeList.from_dict(read_config("xray/nodes.json"))
    nodes.nodes = list(proxy.nodes)
    write_config("xray/nodes.json", nodes.to_dict())
    routing = read_config("xray/routing.json")
    routing["is_proxy_enabled"] = proxy.is_enabled
    routing["is_local_proxy_enabled"] = proxy.is_enabled and proxy.is_local
    routing["is_socks_proxy_enabled"] = proxy.is_socks_proxy_enabled
    routing["socks_proxy_port"] = proxy.socks_proxy_port
    routing["is_socks_direct_enabled"] = proxy.is_socks_direct_enabled
    routing["socks_direct_port"] = proxy.socks_direct_port
    write_config("xray/routing.json", routing)


def _enrollment_link(password: str) -> tuple:
    """One enrollment link, minted by the panel that has just started.

    The token lives in the panel's own memory, so this asks the panel for it
    rather than writing one: a link nothing knows about would be refused by
    the machine that pasted it.

    Args:
        password: The panel password, to open a session with.

    Returns:
        The link and an empty note, or an empty link and why there is none.
    """
    if is_dev_root_set():
        return "", "No panel is running under --dev; start one with `nhub --dev run`."
    base = f"http://127.0.0.1:{_configured_port()}"
    # The panel was started a moment ago and binds its socket when uvicorn is
    # ready, not when systemd returns, so the first ask is often too early.
    deadline = time.monotonic() + SETUP_PANEL_WAIT_S
    while True:
        try:
            session = _post(f"{base}{SETUP_LOGIN_PATH}", {"password": password})
            cookie = session.headers.get("set-cookie", "").split(";")[0]
            minted = _post(
                f"{base}{SETUP_ENROLLMENT_PATH}", {"name": ""}, cookie=cookie
            )
            return json.loads(minted.read())["link"], ""
        except (OSError, ValueError, KeyError) as error:
            if time.monotonic() >= deadline:
                return "", (
                    f"The panel did not answer in {SETUP_PANEL_WAIT_S:.0f}s "
                    f"({error}); its Devices page mints a link."
                )
            time.sleep(SETUP_PANEL_POLL_S)


def _post(url: str, body: dict, *, cookie: str = ""):
    """One JSON POST to the panel on loopback.

    Args:
        url: Where to post.
        body: What to send.
        cookie: A session cookie, for the calls that need one.

    Returns:
        The open response.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if cookie:
        request.add_header("Cookie", cookie)
    return urllib.request.urlopen(request, timeout=SETUP_PANEL_TIMEOUT_S)


def _configured_port() -> int:
    """The port the panel was told to listen on."""
    return read_config("web/settings.json").get("listen_port", WEB_DEFAULT_LISTEN_PORT)


def _panel_url() -> str:
    """Where the panel answers, as the machine in front of it would reach it.

    Returns:
        The LAN address a served interface carries, and the hostname when no
        interface has been given a LAN role yet.
    """
    port = _configured_port()
    for interface in _network_config().interfaces:
        if interface.role == "lan" and interface.lan.address:
            return f"http://{interface.lan.address}:{port}"
    return f"http://{socket.gethostname()}:{port}"


def _step_cliproxyapi(reporter: InstallReporter) -> tuple[str, bool]:
    result = CliproxyApiProvisioner().provision(report=reporter.note)
    if result.is_changed:
        reporter.note("add providers on the panel's Credentials page")
    return result.message, result.is_changed


def _step_required_packages(reporter: InstallReporter) -> tuple[str, bool]:
    """Check what the hub cannot run without is here, and install nothing.

    A package declares these as its dependencies, so on a packaged machine the
    package manager installed them before anything of the hub was running —
    which is the only moment when taking NetworkManager down costs nothing. A
    checkout has no package, so it is told what to run. The division is in
    design/install.md.

    Args:
        reporter: Where progress lines go.

    Returns:
        What was found, and False: this step never changes the machine.

    Raises:
        CommandError: When something the hub cannot run without is missing.
    """
    controller = package_manager.current()
    wanted = package_manager.packages_for(controller.family, SYSTEM_RUNTIME_PACKAGES)
    if not is_packaged():
        wanted += package_manager.packages_for(
            controller.family, SYSTEM_CHECKOUT_PACKAGES
        )
    missing = [name for name in wanted if not controller.is_installed(name)]
    if not missing:
        return f"{len(wanted)} present", False
    raise CommandError(
        f"missing: {', '.join(missing)}\n"
        f"  install them first: {controller.install_command(tuple(missing))}"
    )


def _step_fail2ban(reporter: InstallReporter) -> tuple[str, bool]:
    """Point fail2ban at SSH with the escalating ban ladder."""
    if (
        SYSTEM_FAIL2BAN_JAIL_PATH.is_file()
        and SYSTEM_FAIL2BAN_JAIL_PATH.read_text(encoding="utf-8")
        == SYSTEM_FAIL2BAN_JAIL
    ):
        return "already guarding ssh", False
    SYSTEM_FAIL2BAN_JAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_FAIL2BAN_JAIL_PATH.write_text(SYSTEM_FAIL2BAN_JAIL, encoding="utf-8")
    run(["systemctl", "enable", "--now", "fail2ban"], is_checked=False)
    run(["systemctl", "restart", "fail2ban"], is_checked=False)
    reporter.note("ssh failures now ban the source, 30 seconds up to a day")
    return "ssh guarded", True


def _step_users_and_dirs(reporter: InstallReporter) -> tuple[str, bool]:
    is_changed = False
    if not run(["id", SYSTEM_XRAY_USER], is_checked=False).is_success:
        run(
            [
                "useradd",
                "--system",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                SYSTEM_XRAY_USER,
            ]
        )
        is_changed = True
    # The layout is in docs/standard/design/files.md: configuration under
    # /etc, everything a render produces or a service accumulates under
    # /var/lib, logs under /var/log.
    for directory in (
        UTILS_CONFIG_DIR,
        UTILS_GENERATED_DIR,
        UTILS_GEODATA_DIR,
        UTILS_LOG_DIR,
        SAMBA_DEFAULT_SHARE_DIR,
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            is_changed = True
    shutil.chown(UTILS_LOG_DIR, user=SYSTEM_XRAY_USER)
    # The service writes these as the xray user. Anything root left behind here
    # would be unopenable to it, so ownership is corrected rather than assumed.
    for log_path in UTILS_LOG_DIR.glob("xray_*.log"):
        shutil.chown(log_path, user=SYSTEM_XRAY_USER)
    SAMBA_DEFAULT_SHARE_DIR.chmod(0o2775)
    return ("created user and directories" if is_changed else "present"), is_changed


def _step_python_env(reporter: InstallReporter) -> tuple[str, bool]:
    if is_packaged():
        return "carried by the package", False
    interpreter = venv_python()
    is_changed = False
    if not interpreter.is_file():
        reporter.note(f"creating a virtual environment in {interpreter.parent.parent}")
        run(
            [sys.executable, "-m", "venv", str(interpreter.parent.parent)],
            timeout_s=180,
        )
        is_changed = True
    probe = run(
        [str(interpreter), "-c", "import uvicorn, fastapi, asyncssh, psutil"],
        is_checked=False,
    )
    if probe.is_success and not is_changed:
        return "dependencies present", False
    reporter.note("installing panel dependencies from pyproject.toml")
    run(
        [str(interpreter), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        timeout_s=300,
    )
    run(
        [
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--quiet",
            "-e",
            str(project_root().parent),
        ],
        timeout_s=900,
    )
    return "environment ready", True


def _step_xray_core(reporter: InstallReporter) -> tuple[str, bool]:
    is_changed = False
    if not Path(XRAY_BINARY).is_file():
        if is_packaged():
            raise CommandError(
                f"the package should carry xray at {XRAY_BINARY} and it is not "
                f"there; reinstall the package rather than fetching one"
            )
        reporter.note(f"downloading xray-core {XRAY_VERSION} (~15 MB)")
        _fetch_xray_binary()
        is_changed = True
    for file_name, pin in XRAY_GEODATA.items():
        if (UTILS_GEODATA_DIR / file_name).is_file():
            continue
        if is_packaged():
            raise CommandError(
                f"the package should carry {file_name} in {UTILS_GEODATA_DIR} "
                f"and it is not there; reinstall the package"
            )
        reporter.note(f"downloading {file_name}")
        _fetch_pinned(pin["url"], pin["sha256"], UTILS_GEODATA_DIR / file_name)
        is_changed = True
    if not is_changed:
        version = run([XRAY_BINARY, "version"], is_checked=False).stdout
        return version.splitlines()[0] if version else "present", False
    return f"xray {XRAY_VERSION} and the databases", True


def _fetch_xray_binary() -> None:
    """Put the pinned xray release where the package would have put it.

    A checkout has no package to carry it. The vendor's install script is
    GPL-3.0 and installs under /usr/local, which is neither the hub's to use
    nor a licence it may distribute, so the release archive is taken directly.

    Raises:
        RuntimeError: On a machine the vendor publishes no build for.
    """
    require_architecture(XRAY_SUPPORTED_ARCHITECTURES, "xray")
    architecture = machine_architecture()
    target = Path(XRAY_BINARY)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir) / "xray.zip"
        _fetch_pinned(
            XRAY_DOWNLOAD_URL.format(
                version=XRAY_VERSION,
                asset_arch=XRAY_ASSET_ARCHITECTURES[architecture],
            ),
            XRAY_SHA256[architecture],
            archive,
        )
        with zipfile.ZipFile(archive) as bundle:
            # Only the binary: the databases beside it in the release are a
            # different set from the one the hub carries.
            bundle.extract(XRAY_BINARY_NAME, workdir)
        shutil.move(str(Path(workdir) / XRAY_BINARY_NAME), target)
    target.chmod(0o755)


def _fetch_pinned(url: str, sha256: str, target: Path) -> None:
    """Download one file and refuse anything but the pinned bytes.

    Args:
        url: What to fetch.
        sha256: The digest the file must have.
        target: Where to write it.

    Raises:
        CommandError: If what arrives is not what was pinned.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        staged = Path(workdir) / target.name
        run(["curl", "-fL", "--retry", "2", "-o", str(staged), url], timeout_s=600)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        if digest != sha256:
            raise CommandError(f"{url} came back as {digest}, not {sha256}")
        shutil.move(str(staged), target)


def _step_config_files(reporter: InstallReporter) -> tuple[str, bool]:
    created = []
    for relative_path in CONFIG_FILES:
        real_path = UTILS_CONFIG_DIR / relative_path
        if real_path.is_file():
            continue
        example_path = UTILS_EXAMPLES_DIR / relative_path.replace(
            ".json", ".example.json"
        )
        if not example_path.is_file():
            raise CommandError(f"missing example config {example_path}")
        real_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(example_path, real_path)
        real_path.chmod(0o600)
        created.append(relative_path)
    if not created:
        return f"{len(CONFIG_FILES)} files present", False
    reporter.note(f"copied from examples: {', '.join(created)}")
    return f"created {len(created)}", True


def _step_systemd_units(reporter: InstallReporter) -> tuple[str, bool]:
    written = SystemdUnitInstaller().install()
    is_changed = bool(written)
    for unit, note in DISTRIBUTION_UNITS_MASKED.items():
        if _mask_distribution_unit(reporter, unit, note):
            is_changed = True
    return (f"wrote {', '.join(written)}" if written else "unchanged"), is_changed


def _mask_distribution_unit(reporter: InstallReporter, unit: str, note: str) -> bool:
    """Stop a packaged unit competing with the gateway's own.

    Args:
        reporter: Where the note goes when the unit had to be masked.
        unit: The distribution's unit name.
        note: What to say about it, in the words :data:`DISTRIBUTION_UNITS_MASKED`
            gives.

    Returns:
        True when the unit had to be masked.
    """
    state = run(["systemctl", "is-enabled", unit], is_checked=False).stdout.strip()
    if state in ("masked", "masked-runtime", ""):
        return False
    run(["systemctl", "disable", "--now", unit], is_checked=False)
    run(["systemctl", "mask", unit], is_checked=False)
    reporter.note(note)
    return True


# Units a distribution enables for a package the hub carries its own unit
# for. Both would run the same daemon on the same hardware, and the one the
# hub did not write reads a configuration nobody generated.
DISTRIBUTION_UNITS_MASKED = {
    # Installing hostapd brings a system-wide unit reading
    # /etc/hostapd/hostapd.conf, enabled by default with nothing to read. If
    # it ever did have something, it would take the radio the gateway's
    # per-interface unit wants.
    "hostapd.service": (
        "masked the packaged hostapd unit; the gateway runs its own per radio"
    ),
    # The packaged dnsmasq holds port 53 with a configuration the hub did not
    # write, which is what stops the hub's own from starting at all.
    "dnsmasq.service": (
        "masked the packaged dnsmasq unit; the gateway runs its own on the "
        "configuration it generates"
    ),
}


def _network_config() -> RouterNetworkConfig:
    return RouterNetworkConfig.from_dict(read_config("router/network.json"))


def _step_interfaces(reporter: InstallReporter) -> tuple[str, bool]:
    network = _network_config()
    if not network.interfaces:
        reporter.note(
            "no interface has a role yet; open the Network tab to assign them"
        )
        return "nothing configured", False
    changes = RouterInterfaceApplier(network=network).apply_all()
    if not changes:
        return "already as configured", False
    for change in changes:
        reporter.note(change)
    return f"{len(changes)} interface changes", True


def _step_render_all(reporter: InstallReporter) -> tuple[str, bool]:
    render_script = UTILS_PACKAGE_ROOT / "cli" / "apply.py"
    result = run(
        [sys.executable, str(render_script), "--skip-apply"],
        timeout_s=120,
        is_checked=False,
    )
    if not result.is_success:
        raise CommandError(
            f"rendering failed; fix config/ and re-run:\n{result.stdout}{result.stderr}"
        )
    return f"generated {UTILS_GENERATED_DIR}", True


def _step_enable_services(reporter: InstallReporter) -> tuple[str, bool]:
    controller = SystemdServiceController()
    enabled = []
    for name in SETUP_CORE_SERVICES:
        status = controller.status(name)
        if not status.is_installed or status.is_enabled:
            continue
        controller.control(name, "enable")
        enabled.append(name)
    if not enabled:
        return "already enabled", False
    return f"enabled {', '.join(enabled)}", True


def _step_start_services(
    reporter: InstallReporter, *, names: tuple = SETUP_CORE_SERVICES
) -> tuple[str, bool]:
    controller = SystemdServiceController()
    started = []
    for name in names:
        status = controller.status(name)
        if not status.is_installed:
            continue
        controller.control(name, "restart")
        started.append(name)
    return f"restarted {', '.join(started)}", True


# Defined here, after the functions it names. Everything the appliance is not
# itself without: routing, the proxy core and the AI gateway. Samba, Gitea,
# NetBird, podman and ZFS install themselves from the panel's Services page.
CORE_STEPS = (
    ("Checking the packages the hub needs", _step_required_packages),
    ("Guarding SSH with fail2ban", _step_fail2ban),
    ("Creating service user and directories", _step_users_and_dirs),
    ("Preparing the Python environment", _step_python_env),
    ("Installing xray-core and geodata", _step_xray_core),
    ("Preparing config/ from examples", _step_config_files),
    ("Installing systemd units", _step_systemd_units),
    ("Applying the interface roles", _step_interfaces),
    ("Rendering and applying configuration", _step_render_all),
    ("Enabling services at boot", _step_enable_services),
    ("Starting services", _step_start_services),
    ("Installing the AI gateway", _step_cliproxyapi),
)

if __name__ == "__main__":
    sys.exit(main())
