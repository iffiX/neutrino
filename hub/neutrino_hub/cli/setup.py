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
import urllib.request
import zipfile
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

from neutrino_hub.cli.password import is_password_set, store_password
from neutrino_hub.cli.reporter import InstallReporter
from neutrino_hub.cli import wizard

# --- config ---
# What the panel listens on before anybody has said otherwise.
SETUP_DEFAULT_PORT = 8080
# What the panel is asked for, on loopback, once it is running.
SETUP_LOGIN_PATH = "/api/auth/login"
SETUP_ENROLLMENT_PATH = "/api/devices/enrollment"
SETUP_PANEL_TIMEOUT_S = 10
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
    try:
        answers = _answers(arguments)
    except wizard.WizardAborted as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    steps = [step for step in CORE_STEPS if step[1] not in _skipped_steps()]
    reporter = InstallReporter(
        total_step_count=len(steps) + 1,
        is_color_enabled=(not os.environ.get("NO_COLOR") and sys.stdout.isatty()),
    )
    return _setup(reporter, steps, answers)


def _answers(arguments):
    """What this run was told, however it was told.

    Args:
        arguments: The parsed command line.

    Returns:
        The answers to act on.

    Raises:
        WizardAborted: On an answers document that cannot be used, or a
            wizard nobody finished.
    """
    if arguments.stdin:
        return wizard.from_document(_parsed(sys.stdin.read(), "standard input"))
    if arguments.json:
        path = Path(arguments.json)
        try:
            return wizard.from_document(
                _parsed(path.read_text(encoding="utf-8"), str(path))
            )
        except OSError as error:
            raise wizard.WizardAborted(str(error)) from error
    return wizard.ask()


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


def _setup(reporter: InstallReporter, steps: list, answers) -> int:
    """Run every step, then store the password and hand the box over.

    Args:
        reporter: Where progress lines go.
        steps: The step table to run, in order.
        answers: What the wizard collected.

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
            # placeholder nodes they describe.
            write_config("router/network.json", answers.network.to_dict())
            _write_proxy(answers.proxy)

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
    SystemdServiceController().control("web", "restart")
    reporter.done("stored")

    panel_url = _panel_url()
    link, note = _enrollment_link(answers.password)
    wizard.finish(panel_url=panel_url, link=link, note=note, joined=_joined_devices)
    return 0


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


def _write_proxy(proxy) -> None:
    """Put the proxy screen's answers into `config/xray/`.

    Args:
        proxy: What the wizard collected.
    """
    nodes = XrayNodeList(nodes=list(proxy.nodes))
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
    try:
        session = _post(f"{base}{SETUP_LOGIN_PATH}", {"password": password})
        cookie = session.headers.get("set-cookie", "").split(";")[0]
        minted = _post(f"{base}{SETUP_ENROLLMENT_PATH}", {"name": ""}, cookie=cookie)
        return json.loads(minted.read())["link"], ""
    except (OSError, ValueError, KeyError):
        return "", "The panel did not answer yet; its Devices page mints a link."


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
    return read_config("web/settings.json").get("listen_port", SETUP_DEFAULT_PORT)


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
    if _mask_distribution_hostapd(reporter):
        is_changed = True
    return (f"wrote {', '.join(written)}" if written else "unchanged"), is_changed


def _mask_distribution_hostapd(reporter: InstallReporter) -> bool:
    """Stop the packaged hostapd unit competing with the gateway's own.

    Installing hostapd brings a system-wide ``hostapd.service`` that reads
    /etc/hostapd/hostapd.conf and is enabled by default. It is not ours, it has
    no configuration to read, and if it ever did it would take the radio the
    gateway's per-interface unit wants.

    Returns:
        True when the unit had to be masked.
    """
    state = run(
        ["systemctl", "is-enabled", "hostapd.service"], is_checked=False
    ).stdout.strip()
    if state in ("masked", "masked-runtime", ""):
        return False
    run(["systemctl", "disable", "--now", "hostapd.service"], is_checked=False)
    run(["systemctl", "mask", "hostapd.service"], is_checked=False)
    reporter.note(
        "masked the packaged hostapd unit; the gateway runs its own per radio"
    )
    return True


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
    for name in ("router", "xray", "dnsmasq", "web"):
        status = controller.status(name)
        if not status.is_installed or status.is_enabled:
            continue
        controller.control(name, "enable")
        enabled.append(name)
    if not enabled:
        return "already enabled", False
    return f"enabled {', '.join(enabled)}", True


def _step_start_services(reporter: InstallReporter) -> tuple[str, bool]:
    controller = SystemdServiceController()
    started = []
    for name in ("router", "xray", "dnsmasq", "web"):
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
