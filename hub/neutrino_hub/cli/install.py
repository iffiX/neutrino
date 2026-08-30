"""Idempotent bootstrap for the whole gateway.

Normally invoked through the repo's ``install.sh``. Every step checks the system
before it acts, so re-running converges instead of duplicating work:

    sudo ./install.sh
    sudo python scripts/install/main.py --set-password
    python scripts/install/main.py --import-nodes "ss://... vless://..."
"""

import argparse
import getpass
import ipaddress
import os
import secrets
import shutil
import sys
from pathlib import Path

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.routes import RouterInterfaceApplier
from neutrino_hub.system.constants import (
    SYSTEM_APT_PACKAGES,
    SYSTEM_FAIL2BAN_JAIL,
    SYSTEM_FAIL2BAN_JAIL_PATH,
    SYSTEM_SYSTEMD_DIR,
    SYSTEM_VENV_DIR_NAME,
    SYSTEM_XRAY_USER,
)
from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.ops import GiteaConfigApplier, GiteaSecretStore
from neutrino_hub.modules.gitea.provisioner import GiteaProvisioner
from neutrino_hub.modules.gitea.renderer import GiteaConfigRenderer
from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.constants import SAMBA_DEFAULT_SHARE_DIR
from neutrino_hub.modules.samba.ops import SambaConfigApplier, SambaUserManager
from neutrino_hub.modules.samba.provisioner import SambaProvisioner
from neutrino_hub.modules.samba.renderer import SambaConfigRenderer
from neutrino_hub.modules.cliproxy.provisioner import CliproxyProvisioner
from neutrino_hub.modules.netbird.provisioner import NetbirdProvisioner
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_DATA_DIR,
    UTILS_LOG_DIR,
    UTILS_PACKAGE_ROOT,
)
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.subprocess_run import CommandError, run
from neutrino_hub.web.auth import hash_password
from neutrino_hub.modules.xray.constants import XRAY_BINARY
from neutrino_hub.modules.xray.node_config import XrayNodeList, parse_share_link

from neutrino_hub.cli.reporter import InstallReporter

# --- config ---
XRAY_INSTALL_URL = "https://github.com/XTLS/Xray-install/raw/main/install-release.sh"
UNIT_TEMPLATES = {
    "neutrino_router.service": "neutrino_router.service",
    "neutrino_web.service": "neutrino_web.service",
    # Templated by interface: one access point per radio given the LAN role.
    "neutrino_hostapd@.service": "neutrino_hostapd@.service",
}
XRAY_DROPIN_DIR = SYSTEM_SYSTEMD_DIR / "xray.service.d"
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
    """Run the installer or one of its maintenance modes.

    The step tables are defined at the bottom of this file, after the step
    functions they name.

    Returns:
        Process exit status: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--set-password",
        action="store_true",
        help="prompt for the panel password and store its hash, then exit",
    )
    parser.add_argument(
        "--import-nodes",
        metavar="LINKS",
        help="parse whitespace-separated ss:// or vless:// links into nodes.json",
    )
    parser.add_argument(
        "--with-extras",
        action="store_true",
        help="also install NetBird, Gitea, and the Samba share",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="disable coloured output"
    )
    args = parser.parse_args()

    if args.set_password:
        return _set_password()
    if args.import_nodes:
        return _import_nodes(args.import_nodes)

    steps = list(CORE_STEPS)
    if args.with_extras:
        steps.extend(EXTRA_STEPS)
    reporter = InstallReporter(
        total_step_count=len(steps),
        is_color_enabled=(
            not args.no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
        ),
    )
    return _install(reporter, steps)


def _install(reporter: InstallReporter, steps: list) -> int:
    if os.geteuid() != 0:
        print("error: the installer must run as root (use ./install.sh)")
        return 1

    reporter.banner("Neutrino Hub installer")
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

    reporter.checklist(
        "Almost done — finish these by hand:",
        [
            "Fill in config/xray/nodes.json (or: "
            "python scripts/install/main.py --import-nodes '<links>')",
            "Set the panel password: sudo python scripts/install/main.py "
            "--set-password",
            "Join your NetBird network from the panel once it is installed",
            "Re-apply after edits: sudo python scripts/render_all/main.py",
            "Panel: http://192.168.100.1:8080  (docs/standard/misc/config.md explains config/)",
        ],
    )
    return 0


def _step_netbird(reporter: InstallReporter) -> tuple[str, bool]:
    result = NetbirdProvisioner().provision(report=reporter.note)
    if result.is_changed:
        reporter.note("join your network from the panel's NetBird page")
    return result.message, result.is_changed


def _step_cliproxy(reporter: InstallReporter) -> tuple[str, bool]:
    result = CliproxyProvisioner().provision(report=reporter.note)
    if result.is_changed:
        reporter.note("add providers on the panel's Credentials page")
    return result.message, result.is_changed


def _step_gitea(reporter: InstallReporter) -> tuple[str, bool]:
    result = GiteaProvisioner().provision()
    config = GiteaConfig.from_dict(read_config("gitea/gitea.json"))
    config.validate()
    rendered = GiteaConfigRenderer(
        config=config,
        lan_address=_network_config().primary_lan_address,
        secrets=GiteaSecretStore().load(),
    ).render()
    message = GiteaConfigApplier().apply(rendered)
    if result.is_changed:
        reporter.note("enable gitea and create its administrator in the panel")
    return f"{result.message}; {message}", True


def _step_samba(reporter: InstallReporter) -> tuple[str, bool]:
    """Install samba, then render smb.conf through the panel's own pipeline."""
    SambaProvisioner().provision(report=reporter.note)
    config = SambaConfig.from_dict(read_config("samba/samba.json"))
    config.validate()
    subnets = [
        str(ipaddress.ip_network(interface.lan.cidr, strict=False))
        for interface in _network_config().lan_interfaces
    ]
    rendered = SambaConfigRenderer(config=config, lan_subnets=subnets).render()
    SambaUserManager().converge(config.users)
    message = SambaConfigApplier().apply(rendered, config=config)
    if not config.users:
        reporter.note("add share users and set their passwords in the panel")
    return message, True


def _step_apt_packages(reporter: InstallReporter) -> tuple[str, bool]:
    missing = []
    for package in SYSTEM_APT_PACKAGES:
        result = run(["dpkg", "-s", package], is_checked=False)
        if not result.is_success:
            missing.append(package)
    if not missing:
        return f"{len(SYSTEM_APT_PACKAGES)} packages present", False

    # Samba and dnsmasq both ask debconf questions when a terminal is attached,
    # which would hang an unattended install.
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(["apt-get", "update"], timeout_s=300)
    result = run(
        ["apt-get", "install", "-y", "--no-install-recommends", *missing],
        timeout_s=900,
        is_checked=False,
    )
    if not result.is_success:
        # dnsmasq's postinst fails when its stock config collides with the
        # resolved stub on port 53. The package still unpacks, and the render
        # step below replaces that config, so a failed postinst is only fatal
        # if the binary really is missing.
        still_missing = [
            package
            for package in missing
            if not run(["dpkg", "-s", package], is_checked=False).is_success
        ]
        if still_missing:
            raise CommandError(
                f"apt could not install {', '.join(still_missing)}:\n"
                f"{result.stderr or result.stdout}"
            )
        reporter.note("a package postinst failed; the render step below fixes it")
    return f"installed {', '.join(missing)}", True


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
    for directory in (
        UTILS_LOG_DIR,
        SAMBA_DEFAULT_SHARE_DIR,
        Path("/etc/neutrino/generated"),
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
    venv_python = _venv_python()
    is_changed = False
    if not venv_python.is_file():
        reporter.note(f"creating a virtual environment in {venv_python.parent.parent}")
        run(
            [sys.executable, "-m", "venv", str(venv_python.parent.parent)],
            timeout_s=180,
        )
        is_changed = True
    probe = run(
        [str(venv_python), "-c", "import uvicorn, fastapi, asyncssh, psutil"],
        is_checked=False,
    )
    if probe.is_success and not is_changed:
        return "dependencies present", False
    reporter.note("installing panel dependencies from pyproject.toml")
    run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        timeout_s=300,
    )
    run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "-e",
            str(_checkout_root()),
        ],
        timeout_s=900,
    )
    return "environment ready", True


def _step_xray_core(reporter: InstallReporter) -> tuple[str, bool]:
    if Path(XRAY_BINARY).is_file():
        version = run([XRAY_BINARY, "version"], is_checked=False).stdout
        return version.splitlines()[0] if version else "present", False
    reporter.note("downloading xray-core from GitHub, this can take a minute")
    script = run(["curl", "-fsSL", XRAY_INSTALL_URL], timeout_s=120).stdout
    run(["bash", "-s", "--", "install"], input_text=script, timeout_s=600)
    if not Path(XRAY_BINARY).is_file():
        raise CommandError("xray installer finished but the binary is missing")
    return "installed", True


def _step_config_files(reporter: InstallReporter) -> tuple[str, bool]:
    created = []
    for relative_path in CONFIG_FILES:
        real_path = UTILS_CONFIG_DIR / relative_path
        if real_path.is_file():
            continue
        example_path = real_path.with_name(
            real_path.name.replace(".json", ".example.json")
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
    # The units must run the venv interpreter, not whichever python launched the
    # installer: the panel's dependencies live only in the virtual environment.
    python_path = str(_venv_python())
    is_changed = False
    for template_name, unit_name in UNIT_TEMPLATES.items():
        template = (UTILS_DATA_DIR / "services" / template_name).read_text(
            encoding="utf-8"
        )
        rendered = template.replace("@REPO_ROOT@", str(_checkout_root())).replace(
            "@PYTHON@", python_path
        )
        destination = SYSTEM_SYSTEMD_DIR / unit_name
        if (
            destination.is_file()
            and destination.read_text(encoding="utf-8") == rendered
        ):
            continue
        destination.write_text(rendered, encoding="utf-8")
        is_changed = True
    if _mask_distribution_hostapd(reporter):
        is_changed = True
    if is_changed:
        SystemdServiceController().daemon_reload()
    return ("wrote unit files" if is_changed else "unchanged"), is_changed


def _mask_distribution_hostapd(reporter: InstallReporter) -> bool:
    """Stop the packaged hostapd unit competing with the gateway's own.

    Installing hostapd brings a system-wide ``hostapd.service`` that reads
    /etc/hostapd/hostapd.conf and is enabled by default. It is not ours, it has
    no configuration to read, and if it ever did it would take the radio the
    gateway's per-interface unit wants.

    Returns:
        True when the unit had to be masked.
    """
    controller = SystemdServiceController()
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


def _step_xray_dropin(reporter: InstallReporter) -> tuple[str, bool]:
    source = UTILS_DATA_DIR / "services" / "xray_override.conf"
    destination = XRAY_DROPIN_DIR / "neutrino.conf"
    rendered = source.read_text(encoding="utf-8")
    if destination.is_file() and destination.read_text(encoding="utf-8") == rendered:
        return "unchanged", False
    XRAY_DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    SystemdServiceController().daemon_reload()
    return "wrote drop-in", True


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
    render_script = UTILS_PACKAGE_ROOT / "cli" / "render_all.py"
    result = run(
        [sys.executable, str(render_script), "--skip-apply"],
        timeout_s=120,
        is_checked=False,
    )
    if not result.is_success:
        raise CommandError(
            f"rendering failed; fix config/ and re-run:\n{result.stdout}{result.stderr}"
        )
    return "generated /etc/neutrino/generated", True


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


def _set_password() -> int:
    password = getpass.getpass("New panel password: ")
    if len(password) < 8:
        print("error: use at least 8 characters")
        return 1
    if password != getpass.getpass("Repeat: "):
        print("error: passwords do not match")
        return 1
    settings = read_config("web/settings.json")
    settings["admin_password_hash"] = hash_password(password)
    if settings.get("session_secret", "").startswith("PLACEHOLDER"):
        settings["session_secret"] = secrets.token_hex(32)
    write_config("web/settings.json", settings)
    print("password updated; restart the panel to log everyone out")
    return 0


def _import_nodes(links: str) -> int:
    try:
        nodes = [parse_share_link(link) for link in links.split() if link.strip()]
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not nodes:
        print("error: no share links given", file=sys.stderr)
        return 1
    existing = XrayNodeList.from_dict(read_config("xray/nodes.json"))
    existing.nodes = nodes
    write_config("xray/nodes.json", existing.to_dict())
    print(f"imported {len(nodes)} nodes: {', '.join(node.id for node in nodes)}")
    print("apply with: sudo nhub render")
    return 0


def _checkout_root() -> Path:
    """The working copy this package was imported from.

    Only meaningful while installing from a checkout, which is what the
    editable install and the virtual environment below both assume.

    Returns:
        The directory holding ``hub/`` and ``config/``.
    """
    return UTILS_PACKAGE_ROOT.parent.parent


def _venv_python() -> Path:
    return _checkout_root() / SYSTEM_VENV_DIR_NAME / "bin" / "python"


# Defined here, after the functions they name. CORE_STEPS is everything the
# appliance is not itself without — routing, the way back in, and the AI
# gateway; EXTRA_STEPS holds the optional services and runs only with
# --with-extras.
CORE_STEPS = (
    ("Installing system packages", _step_apt_packages),
    ("Guarding SSH with fail2ban", _step_fail2ban),
    ("Creating service user and directories", _step_users_and_dirs),
    ("Preparing the Python environment", _step_python_env),
    ("Installing xray-core and geodata", _step_xray_core),
    ("Preparing config/ from examples", _step_config_files),
    ("Installing systemd units", _step_systemd_units),
    ("Installing the xray drop-in", _step_xray_dropin),
    ("Applying the interface roles", _step_interfaces),
    ("Rendering and applying configuration", _step_render_all),
    ("Enabling services at boot", _step_enable_services),
    ("Starting services", _step_start_services),
    ("Installing NetBird", _step_netbird),
    ("Installing the AI gateway", _step_cliproxy),
)

EXTRA_STEPS = (
    ("Installing Gitea", _step_gitea),
    ("Configuring the Samba share", _step_samba),
)


if __name__ == "__main__":
    sys.exit(main())
