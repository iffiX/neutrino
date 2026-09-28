"""The root half of joining an EasyTier network, run under ``pkexec``.

    overlay_helper easytier up --network NAME --secret-file FILE --peer URI --hostname NAME
    overlay_helper easytier down --network NAME

polkit hands the helper the caller's uid in ``PKEXEC_UID``. The secret file
must be a 0600 regular file of the caller's under their home; the helper
reads the secret from it, renders ``/etc/neutrino_client/easytier/<NAME>.toml``
as root, mode 0600, and restarts the daemon. ``down`` removes that one file
and restarts the daemon while another network's file is left, and stops it
when none is. Nothing on the argument vector names a path the helper writes.

Exit statuses are the typed codes in ``constants.CLIENT_OVERLAY_HELPER_EXIT_CODES``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

from neutrino_client.constants import (
    CLIENT_EASYTIER_CONFIG_DIR_LINUX,
    CLIENT_EASYTIER_CONFIG_SUFFIX,
    CLIENT_EASYTIER_SERVICE_LINUX,
)
from neutrino_client.core.easytier_config import (
    is_hostname,
    is_network_name,
    is_peer_uri,
    render_easytier_config,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_CALLER_UNKNOWN = 2
EXIT_NETWORK_INVALID = 3
EXIT_PEER_INVALID = 4
EXIT_SECRET_MISSING = 5
EXIT_RESTART_FAILED = 6

SYSTEMCTL_TIMEOUT_S = 60
# The most a secret file may hold.
SECRET_LIMIT_BYTES = 4096


def run(
    argv: list,
    environ: dict,
    *,
    run_command=subprocess.run,
    config_dir: str = CLIENT_EASYTIER_CONFIG_DIR_LINUX,
) -> int:
    """Carry out one helper invocation.

    Args:
        argv: The arguments after the program name.
        environ: The process environment, read for ``PKEXEC_UID``.
        run_command: The ``subprocess.run`` to drive systemctl with.
        config_dir: The directory the daemon reads its networks from.

    Returns:
        The exit status.
    """
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if arguments.provider != "easytier" or arguments.command not in ("up", "down"):
        return EXIT_USAGE
    caller = _caller(environ)
    if caller is None:
        return EXIT_CALLER_UNKNOWN
    if not is_network_name(arguments.network):
        return EXIT_NETWORK_INVALID
    if arguments.command == "up":
        return _up(caller, arguments, run_command, config_dir)
    return _down(arguments, run_command, config_dir)


def main() -> int:
    """Run as ``python -m neutrino_client.cli.overlay_helper``."""
    return run(sys.argv[1:], dict(os.environ))


def network_files(config_dir: str) -> list:
    """The network files the daemon would read, by name.

    Args:
        config_dir: The daemon's configuration directory.

    Returns:
        The file names ending in the configuration suffix, sorted; empty
        when the directory is missing.
    """
    try:
        names = os.listdir(config_dir)
    except OSError:
        return []
    return sorted(
        name for name in names if name.endswith(CLIENT_EASYTIER_CONFIG_SUFFIX)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overlay_helper", add_help=False)
    parser.add_argument("provider")
    commands = parser.add_subparsers(dest="command")
    up = commands.add_parser("up", add_help=False)
    up.add_argument("--network", required=True)
    up.add_argument("--secret-file", required=True)
    up.add_argument("--peer", required=True)
    up.add_argument("--hostname", required=True)
    down = commands.add_parser("down", add_help=False)
    down.add_argument("--network", required=True)
    parser.set_defaults(command="")
    return parser


def _caller(environ: dict):
    """The account polkit says asked, or None without a usable ``PKEXEC_UID``."""
    raw = str(environ.get("PKEXEC_UID", ""))
    if not raw.isdigit() or pwd is None:
        return None
    try:
        return pwd.getpwuid(int(raw))
    except KeyError:
        return None


def _up(caller, arguments, run_command, config_dir: str) -> int:
    if not is_peer_uri(arguments.peer):
        return EXIT_PEER_INVALID
    if not is_hostname(arguments.hostname):
        return EXIT_USAGE
    secret = _read_secret(caller, arguments.secret_file)
    if not secret:
        return EXIT_SECRET_MISSING
    text = render_easytier_config(
        network_name=arguments.network,
        network_secret=secret,
        peer=arguments.peer,
        hostname=arguments.hostname,
    )
    try:
        _write_root_file(config_dir, arguments.network, text)
    except OSError as error:
        sys.stderr.write(f"{error}\n")
        return EXIT_RESTART_FAILED
    return _systemctl("restart", run_command)


def _down(arguments, run_command, config_dir: str) -> int:
    path = os.path.join(config_dir, arguments.network + CLIENT_EASYTIER_CONFIG_SUFFIX)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        sys.stderr.write(f"{error}\n")
        return EXIT_RESTART_FAILED
    if network_files(config_dir):
        return _systemctl("restart", run_command)
    return _systemctl("stop", run_command)


def _read_secret(caller, path: str) -> str:
    """The secret in the caller's own 0600 file under their home; empty otherwise."""
    path = str(path)
    if not os.path.isabs(path):
        return ""
    real = os.path.realpath(path)
    home = os.path.realpath(caller.pw_dir).rstrip("/")
    if not home or not real.startswith(home + "/"):
        return ""
    try:
        facts = os.stat(real)
    except OSError:
        return ""
    if not os.path.isfile(real):
        return ""
    if facts.st_uid != caller.pw_uid or facts.st_mode & 0o777 != 0o600:
        return ""
    try:
        with open(real, "r", encoding="utf-8") as stream:
            return stream.read(SECRET_LIMIT_BYTES).strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _write_root_file(config_dir: str, network: str, text: str) -> None:
    """Write one network's file as root, 0600, replaced in one step."""
    os.makedirs(config_dir, mode=0o700, exist_ok=True)
    os.chmod(config_dir, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=config_dir, prefix=".network.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o600)
        os.replace(
            temporary, os.path.join(config_dir, network + CLIENT_EASYTIER_CONFIG_SUFFIX)
        )
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _systemctl(verb: str, run_command) -> int:
    """Restart or stop the daemon; ``EXIT_RESTART_FAILED`` with its words otherwise."""
    command = ["systemctl", verb, CLIENT_EASYTIER_SERVICE_LINUX]
    try:
        result = run_command(
            command, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"{error}\n")
        return EXIT_RESTART_FAILED
    if result.returncode != 0:
        sys.stderr.write((result.stderr or result.stdout or "").strip()[-400:] + "\n")
        return EXIT_RESTART_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
