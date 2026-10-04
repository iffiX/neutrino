"""Return part of the box to a fresh state.

    sudo nhub reset                 # what can be reset, and nothing done
    sudo nhub reset password
    sudo nhub reset all

Resetting is always named: the bare command lists and stops, so nothing here
is destroyed by a command that was meant to ask a question.

``all`` leaves the box as it was before anybody set it up, which includes
nothing of the hub's running: it hands the network back, returns every config
to its example, clears the password, and then stops the services. The machine
is reached over SSH until ``nhub setup`` runs again.
"""

import argparse
import subprocess
import shutil
import sys

from neutrino_hub.cli.stop import stop, stop_everything, stop_service
from neutrino_hub.cli.password import (
    clear_password,
    read_new_password,
    store_password,
)
from neutrino_hub import edition
from neutrino_hub.modules.firewall.ops import hand_back_firewall
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.controller import router_lock
from neutrino_hub.modules.router.routes import hand_back
from neutrino_hub.platforms.detect import hub_platform, is_linux, process_controller
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import copy_example, read_config
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_EXAMPLES_DIR,
    UTILS_LOG_ROOT,
    UTILS_STATE_ROOT,
)

# --- config ---
# What `all` clears that no example replaces: material a running box collected
# rather than a file it was given.
RESET_COLLECTED_PATHS = (
    "devices/known_hosts",
    "devices/packages",
    # The agent channel's certificate and key go with the fleet that pinned
    # them; the next setup generates a fresh identity for its own.
    "web/agent_tls",
    # The panel's certificate authority, which browsers trusted for this box;
    # the next setup generates another.
    "web/panel_tls",
    # The id clients group this hub by; the next setup generates a new one.
    "web/identity.json",
    # Sealed under the vault's data key, which this reset also clears: left
    # behind, it is a file the next owner's vault cannot open, and the AI
    # gateway's management API stays unreachable until somebody deletes it
    # by hand.
    "cliproxyapi/management_key.sealed",
)
# The files under /var/lib/neutrino/hub that `all` clears for the same reason:
# state a fresh box generates for itself, and the next owner must not inherit.
# The vault's data key in particular — left behind, it opens whatever store
# the next owner restores under the same wrap. The node health file is not a
# secret; it is this box's readings of nodes the next owner does not have.
# An open enrolment ticket would join a machine to the next owner's hub.
RESET_STATE_PATHS = (
    "session.secret",
    "vault.key",
    "agent_tls_key.pem",
    "panel_tls_certificate.pem",
    "panel_tls_key.pem",
    "xray_node_health.json",
    "enrollment_tickets.json",
    # The children the service runs on macOS and Windows, and their start
    # lines; the next setup enables them again.
    "services.json",
)
# Directories under the state root the hub filled itself. The module cache is
# a cache in the strict sense, so handing the box back costs the next owner a
# download and nothing else. The AI gateway's directory is the opposite kind:
# the accounts somebody signed in with live there as refresh tokens, and a
# box handed on with them is a box that keeps signing in as the last owner.
# `hub_update` holds the packages the hub downloaded to update itself and the
# record of the last update, both this box's own. `agent_cache` is in neither
# list: what the hub's own package laid there is the package manager's to
# remove.
RESET_STATE_DIRS = ("agent_module_cache", "cliproxyapi", "hub_update", "netbird")
# Where every device's desired state lives, one directory per device. A
# reset forgets them with the tokens: they describe machines the next owner
# has not enrolled.
RESET_DEVICES_DIR = "devices"
RESET_EXAMPLE_SUFFIX = ".example.json"
# Examples of files the next setup generates; no reset copies them over.
RESET_GENERATED_EXAMPLES = ("web/identity.example.json",)
RESET_PANEL_UNIT = "web"
RESET_TARGETS = {
    "password": "the panel password, leaving every other setting alone",  # scan: allow
    "all": "every module's config, the panel password, and the keys and tokens "
    "this box collected; stops the hub's services too",
}


def main() -> int:
    """Reset what was named.

    Returns:
        Process exit status: 0 on success, 1 on refusal, 2 when nothing was
        named.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "target", nargs="?", choices=sorted(RESET_TARGETS), help="what to reset"
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read the new password from standard input rather than prompting",
    )
    arguments = parser.parse_args()

    if arguments.target is None:
        print("nhub reset <target>, where target is one of:\n")
        for name, description in sorted(RESET_TARGETS.items()):
            print(f"  {name:<10}{description}")
        print("\nNothing was reset.")
        return 2

    platform = hub_platform()
    if not platform.is_elevated():
        print(
            f"error: reset must run as {platform.elevation_word} "
            f"({platform.elevation_hint(f'reset {arguments.target}')})",
            file=sys.stderr,
        )
        return 1

    if arguments.target == "password":
        return _reset_password(is_stdin=arguments.stdin)
    return _reset_all()


def _reset_password(*, is_stdin: bool) -> int:
    """Store a new panel password and log everyone out.

    Args:
        is_stdin: Read the password from standard input rather than prompting.

    Returns:
        Process exit status.
    """
    try:
        store_password(read_new_password(is_stdin=is_stdin))
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    panel = _restart_panel()
    if panel:
        print(panel, file=sys.stderr)
    print("password updated; everyone signed in has been signed out")
    return 0


def _reset_all() -> int:
    """Return every config to its example and forget what the box collected.

    Returns:
        Process exit status.
    """
    # The panel and the router unit first. The panel's dnsmasq restart starts
    # the router unit again, and a running router unit applies the old
    # configuration on the next link event, taking back what is handed back.
    if is_linux():
        stop(["web", "router"])
    else:
        stop_service()
    with router_lock():
        network = _hand_back_network()
    collected = _forget_collected() + _forget_logs()
    restored = _restore_examples()
    clear_password()

    print(f"restored {restored} config files from their examples")
    if collected:
        print(f"removed {', '.join(collected)}")
    for line in network:
        print(line)
    # Last, and stopped rather than restarted. A reset is the box before
    # anybody set it up, and on that box nothing of the hub's is running: the
    # panel has no password to let anyone in with, and the services are
    # configured from the examples rather than from what this machine was.
    # Leaving the panel up would leave the one part of a reset box that
    # answers, on a configuration nobody chose.
    stop_everything()
    print("the panel password is cleared; run `sudo nhub setup`")
    return 0


def _hand_back_network() -> list:
    """Stop driving the machine's network, before the configuration goes.

    First, while `config/` still names the interfaces that were being driven:
    once it has been replaced by the examples there is nothing left saying
    which radios and uplinks the hub had units running on.

    Nothing is restored, because nothing was taken. Every address stays where
    it is, and whatever managed this machine before is started by whoever
    starts it — the hub only stops being the one doing it.

    In every mode, not only the one that addressed the interfaces: the
    firewall is the hub's own wherever it ran, and the rest of the hand-back
    is already a list of things that are not running on a machine that never
    started them.

    Returns:
        One line per thing stopped, empty on a machine the hub never drove.
        On macOS and Windows, one line per TUN route withdrawn and per
        firewall rule or program taken away.
    """
    if not is_linux():
        notes = []
        for withdraw in edition.hooks("reset_withdraw"):
            try:
                notes += withdraw()
            except OSError as error:
                notes.append(f"tun routes not withdrawn: {error}")
        try:
            return notes + hand_back_firewall()
        except (OSError, subprocess.SubprocessError) as error:
            return notes + [f"firewall not handed back: {command_failure_text(error)}"]
    try:
        network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
    except (FileNotFoundError, ValueError):
        return []
    return hand_back(network)


def _forget_collected() -> list:
    """Delete the keys, tokens and caches no example replaces.

    Returns:
        What was removed, named the way `config/` names it.
    """
    removed = []
    for relative_path in RESET_COLLECTED_PATHS:
        path = UTILS_CONFIG_DIR / relative_path
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            continue
        removed.append(relative_path)
    devices_dir = UTILS_CONFIG_DIR / RESET_DEVICES_DIR
    if devices_dir.is_dir():
        for path in sorted(devices_dir.iterdir()):
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(f"{RESET_DEVICES_DIR}/{path.name}")
    for relative_path in RESET_STATE_PATHS:
        path = UTILS_STATE_ROOT / relative_path
        if path.exists():
            path.unlink()
            removed.append(str(path))
    for relative_path in RESET_STATE_DIRS:
        path = UTILS_STATE_ROOT / relative_path
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
    return removed


def _forget_logs() -> list:
    """Empty the log root, which holds nothing but what the hub wrote.

    The directory itself stays. The accounts that write into it still exist,
    and `nhub setup` is what hands it to them.

    Returns:
        What was removed, by path.
    """
    if not UTILS_LOG_ROOT.is_dir():
        return []
    removed = []
    for path in sorted(UTILS_LOG_ROOT.iterdir()):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    return removed


def _restore_examples() -> int:
    """Write every committed example, without its records, over its real file.

    Returns:
        How many files were written.
    """
    written = 0
    for example_path in sorted(UTILS_EXAMPLES_DIR.rglob(f"*{RESET_EXAMPLE_SUFFIX}")):
        relative = example_path.relative_to(UTILS_EXAMPLES_DIR)
        # A device directory's examples document a shape; no device of the
        # next owner's stands behind them.
        if len(relative.parts) > 2 or relative.as_posix() in RESET_GENERATED_EXAMPLES:
            continue
        real_path = UTILS_CONFIG_DIR / relative.with_name(
            relative.name.replace(RESET_EXAMPLE_SUFFIX, ".json")
        )
        copy_example(example_path, real_path)
        written += 1
    return written


def _restart_panel() -> str:
    """Restart the panel, so no session outlives the change.

    A failure here is reported rather than raised. Everything a reset exists
    to undo has already been undone by the time this runs, and a traceback
    over the last step would say a reset failed when what failed was one
    service coming back — which `systemctl status` can say better.

    Returns:
        What happened, empty when there was nothing to restart.
    """
    controller = SystemdServiceController() if is_linux() else process_controller()
    if not controller.status(RESET_PANEL_UNIT).is_installed:
        return ""
    try:
        controller.control(RESET_PANEL_UNIT, "restart")
    except (subprocess.SubprocessError, OSError) as error:
        return f"the panel did not come back: {command_failure_text(error)}"
    return ""


if __name__ == "__main__":
    sys.exit(main())
