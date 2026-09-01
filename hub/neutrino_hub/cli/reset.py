"""Return part of the box to a fresh state.

    sudo nhub reset                 # what can be reset, and nothing done
    sudo nhub reset password
    sudo nhub reset all

Resetting is always named: the bare command lists and stops, so nothing here
is destroyed by a command that was meant to ask a question.
"""

import argparse
import os
import shutil
import sys

from neutrino_hub.cli.password import (
    PasswordRefused,
    clear_password,
    read_new_password,
    store_password,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.routes import hand_back
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_EXAMPLES_DIR

# --- config ---
# What `all` clears that no example replaces: material a running box collected
# rather than a file it was given.
RESET_COLLECTED_PATHS = (
    "gitea/secrets.json",
    "devices/known_hosts",
    "devices/packages",
    "credentials/ssh_keys",
)
RESET_EXAMPLE_SUFFIX = ".example.json"
RESET_PANEL_UNIT = "web"
RESET_TARGETS = {
    "password": "the panel password, leaving every other setting alone",  # scan: allow
    "all": "every module's config, the panel password, and the keys and tokens "
    "this box collected",
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

    if os.geteuid() != 0:
        print(
            f"error: reset must run as root (sudo nhub reset {arguments.target})",
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
    except (PasswordRefused, FileNotFoundError) as error:
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
    network = _hand_back_network()
    collected = _forget_collected()
    restored = _restore_examples()
    clear_password()
    panel = _restart_panel()

    print(f"restored {restored} config files from their examples")
    if collected:
        print(f"removed {', '.join(collected)}")
    for line in network:
        print(line)
    if panel:
        print(panel)
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

    Returns:
        One line per thing stopped, empty on a machine the hub never drove.
    """
    try:
        network = RouterNetworkConfig.from_dict(read_config("router/network.json"))
    except (FileNotFoundError, ValueError):
        return []
    if not network.is_addressing_owned:
        return ["this machine addressed its own interfaces; nothing to hand back"]
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
    return removed


def _restore_examples() -> int:
    """Copy every committed example over the real file beside it.

    Returns:
        How many files were written.
    """
    written = 0
    for example_path in sorted(UTILS_EXAMPLES_DIR.rglob(f"*{RESET_EXAMPLE_SUFFIX}")):
        relative = example_path.relative_to(UTILS_EXAMPLES_DIR)
        real_path = UTILS_CONFIG_DIR / relative.with_name(
            relative.name.replace(RESET_EXAMPLE_SUFFIX, ".json")
        )
        real_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(example_path, real_path)
        real_path.chmod(0o600)
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
    controller = SystemdServiceController()
    if not controller.status(RESET_PANEL_UNIT).is_installed:
        return ""
    try:
        controller.control(RESET_PANEL_UNIT, "restart")
    except CommandError as error:
        return f"the panel did not come back: {error}"
    return ""


if __name__ == "__main__":
    sys.exit(main())
