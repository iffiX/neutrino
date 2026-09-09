"""The root half of a mount, run under ``pkexec``.

    mount_helper mount --share //host/name --location PATH --credentials FILE
    mount_helper unmount --location PATH

polkit hands the helper the caller's uid in ``PKEXEC_UID``; everything the
helper trusts derives from that. The location must be an empty directory the
caller owns under their own home, the credentials file a 0600 regular file
of theirs under that home, and the mount lands with their uid and gid. An
unmount touches only a CIFS mount under the caller's home. Nothing on the
argument vector can widen any of that.

Exit statuses are the typed codes in ``constants.CLIENT_MOUNT_HELPER_EXIT_CODES``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_CALLER_UNKNOWN = 2
EXIT_MOUNTPOINT_INVALID = 3
EXIT_MOUNTPOINT_NOT_EMPTY = 4
EXIT_CREDENTIALS_MISSING = 5
EXIT_MOUNT_FAILED = 6
EXIT_UNMOUNT_FAILED = 7

CIFS_TYPE = "cifs"
MOUNT_TIMEOUT_S = 90
PROC_MOUNTS_PATH = "/proc/mounts"
PROC_MOUNTS_ESCAPES = (
    ("\\", "\\134"),
    (" ", "\\040"),
    ("\t", "\\011"),
    ("\n", "\\012"),
)


def run(argv: list, environ: dict, *, run_command=subprocess.run) -> int:
    """Carry out one helper invocation.

    Args:
        argv: The arguments after the program name.
        environ: The process environment, read for ``PKEXEC_UID``.
        run_command: The ``subprocess.run`` to drive mount and umount with.

    Returns:
        The exit status.
    """
    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    caller = _caller(environ)
    if caller is None:
        return EXIT_CALLER_UNKNOWN
    if arguments.command == "mount":
        return _mount(caller, arguments, run_command)
    return _unmount(caller, arguments, run_command)


def main() -> int:
    """Run as ``python -m neutrino_client.cli.mount_helper``."""
    return run(sys.argv[1:], dict(os.environ))


def is_under(root: str, path: str) -> bool:
    """Whether a real path sits strictly below a directory.

    Args:
        root: The directory.
        path: The path, already real.

    Returns:
        True when the path is inside the directory.
    """
    real_root = os.path.realpath(root).rstrip("/")
    return bool(real_root) and path.startswith(real_root + "/")


def is_cifs_mounted(location: str) -> bool:
    """Whether a CIFS mount stands at a location, read from the kernel.

    Args:
        location: The mount point.

    Returns:
        True when the mount table names the location with the cifs type.
    """
    encoded = location
    for character, escape in PROC_MOUNTS_ESCAPES:
        encoded = encoded.replace(character, escape)
    try:
        with open(PROC_MOUNTS_PATH, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split()
        if len(fields) >= 3 and fields[1] == encoded and fields[2] == CIFS_TYPE:
            return True
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mount_helper", add_help=False)
    commands = parser.add_subparsers(dest="command")
    mount = commands.add_parser("mount", add_help=False)
    mount.add_argument("--share", required=True)
    mount.add_argument("--location", required=True)
    mount.add_argument("--credentials", required=True)
    unmount = commands.add_parser("unmount", add_help=False)
    unmount.add_argument("--location", required=True)
    parser.set_defaults(command="")
    return parser


def _caller(environ: dict):
    """The account polkit says asked, or None.

    Args:
        environ: The process environment.

    Returns:
        The ``pwd`` entry, or None without a usable ``PKEXEC_UID``.
    """
    raw = str(environ.get("PKEXEC_UID", ""))
    if not raw.isdigit() or pwd is None:
        return None
    try:
        return pwd.getpwuid(int(raw))
    except KeyError:
        return None


def _mount(caller, arguments, run_command) -> int:
    if not arguments.command == "mount":
        return EXIT_USAGE
    share = str(arguments.share)
    if not share.startswith("//") or share.count("/") < 3:
        return EXIT_USAGE
    location = _judge_location(caller, arguments.location)
    if location is None:
        return EXIT_MOUNTPOINT_INVALID
    try:
        if os.listdir(location):
            return EXIT_MOUNTPOINT_NOT_EMPTY
    except OSError:
        return EXIT_MOUNTPOINT_INVALID
    credentials = _judge_credentials(caller, arguments.credentials)
    if credentials is None:
        return EXIT_CREDENTIALS_MISSING
    options = f"credentials={credentials},uid={caller.pw_uid},gid={caller.pw_gid}"
    command = ["mount", "-t", CIFS_TYPE, share, location, "-o", options]
    return _run(command, run_command, failure=EXIT_MOUNT_FAILED)


def _unmount(caller, arguments, run_command) -> int:
    if not arguments.command == "unmount":
        return EXIT_USAGE
    location = str(arguments.location)
    if not os.path.isabs(location):
        return EXIT_MOUNTPOINT_INVALID
    real = os.path.realpath(location)
    if not is_under(caller.pw_dir, real) or not is_cifs_mounted(real):
        return EXIT_MOUNTPOINT_INVALID
    return _run(["umount", real], run_command, failure=EXIT_UNMOUNT_FAILED)


def _judge_location(caller, location: str) -> "str | None":
    """The real mount point when it is the caller's empty directory.

    Args:
        caller: The caller's ``pwd`` entry.
        location: The location as given.

    Returns:
        The real path, or None when it is not acceptable.
    """
    location = str(location)
    if not os.path.isabs(location):
        return None
    real = os.path.realpath(location)
    if not is_under(caller.pw_dir, real):
        return None
    try:
        facts = os.stat(real)
    except OSError:
        return None
    if not os.path.isdir(real) or facts.st_uid != caller.pw_uid:
        return None
    return real


def _judge_credentials(caller, path: str) -> "str | None":
    """The real credentials path when it is the caller's own 0600 file.

    Args:
        caller: The caller's ``pwd`` entry.
        path: The path as given.

    Returns:
        The real path, or None when it is not acceptable.
    """
    path = str(path)
    if not os.path.isabs(path):
        return None
    real = os.path.realpath(path)
    if not is_under(caller.pw_dir, real):
        return None
    try:
        facts = os.stat(real)
    except OSError:
        return None
    if not os.path.isfile(real):
        return None
    if facts.st_uid != caller.pw_uid or facts.st_mode & 0o777 != 0o600:
        return None
    return real


def _run(command: list, run_command, *, failure: int) -> int:
    try:
        result = run_command(
            command, capture_output=True, text=True, timeout=MOUNT_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"{error}\n")
        return failure
    if result.returncode != 0:
        sys.stderr.write((result.stderr or result.stdout or "").strip()[-400:] + "\n")
        return failure
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
