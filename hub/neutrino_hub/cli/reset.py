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
from neutrino_hub.system.systemd_ctl import SystemdServiceController
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
        "--password-stdin",
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
        return _reset_password(is_stdin=arguments.password_stdin)
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
    _restart_panel()
    print("password updated; everyone signed in has been signed out")
    return 0


def _reset_all() -> int:
    """Return every config to its example and forget what the box collected.

    Returns:
        Process exit status.
    """
    collected = _forget_collected()
    restored = _restore_examples()
    clear_password()
    _restart_panel()

    print(f"restored {restored} config files from their examples")
    if collected:
        print(f"removed {', '.join(collected)}")
    print("the panel password is cleared; run `sudo nhub setup`")
    return 0


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


def _restart_panel() -> None:
    """Restart the panel, so no session outlives the change."""
    controller = SystemdServiceController()
    if controller.status(RESET_PANEL_UNIT).is_installed:
        controller.control(RESET_PANEL_UNIT, "restart")


if __name__ == "__main__":
    sys.exit(main())
