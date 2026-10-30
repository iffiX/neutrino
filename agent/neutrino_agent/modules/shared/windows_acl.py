"""Access lists on Windows, set with ``icacls.exe``.

Groups are named by their well-known SIDs, so no language's group name
matters. The tool's output is discarded and its exit code read.

Not pure: runs icacls.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import subprocess

WINDOWS_ACL_PROGRAM = "icacls.exe"
WINDOWS_ACL_SYSTEM = "*S-1-5-18"
WINDOWS_ACL_ADMINISTRATORS = "*S-1-5-32-544"
WINDOWS_ACL_USERS = "*S-1-5-32-545"
# What a grant on a directory adds so its files and folders inherit it.
WINDOWS_ACL_INHERITED = "(OI)(CI)"
# Passing through a directory and reading its attributes, on the directory alone.
WINDOWS_ACL_PASS_THROUGH = "(S,X,RA)"


def icacls(run, arguments: list) -> int:
    """Run ``icacls.exe`` once.

    Args:
        run: Runs one command as :func:`subprocess_run.run` does.
        arguments: Its arguments.

    Returns:
        Its exit code.

    Raises:
        OSError: When it cannot start or does not finish.
    """
    try:
        return run([WINDOWS_ACL_PROGRAM, *arguments], is_checked=False).exit_code
    except subprocess.SubprocessError as error:
        raise OSError(f"icacls did not finish: {error}") from error


def grant_account_alone(
    run, path: str, account: str, right: str, *, is_tree: bool
) -> None:
    """Leave one path to an account, SYSTEM and the administrators alone.

    Nothing is inherited from above; the account gets the right named, SYSTEM
    and the administrators full control.

    Args:
        run: Runs one command as :func:`subprocess_run.run` does.
        path: The file or the directory.
        account: The account.
        right: Its right, such as ``M`` or ``R``.
        is_tree: Whether the grants reach what a directory holds.

    Raises:
        OSError: When icacls refuses or cannot run.
    """
    inherited = WINDOWS_ACL_INHERITED if is_tree else ""
    code = icacls(
        run,
        [
            path,
            "/inheritance:r",
            "/grant:r",
            f"{account}:{inherited}{right}",
            f"{WINDOWS_ACL_SYSTEM}:{inherited}F",
            f"{WINDOWS_ACL_ADMINISTRATORS}:{inherited}F",
        ],
    )
    if code != 0:
        raise OSError(f"icacls refused {path}")


def open_to_users(run, directory: str) -> None:
    """Let the Users group read and run one directory and what it holds.

    Args:
        run: Runs one command as :func:`subprocess_run.run` does.
        directory: The directory.

    Raises:
        OSError: When icacls refuses or cannot run.
    """
    code = icacls(
        run, [directory, "/grant", f"{WINDOWS_ACL_USERS}:{WINDOWS_ACL_INHERITED}RX"]
    )
    if code != 0:
        raise OSError(f"icacls exited {code}")


def let_users_through(run, directory: str) -> None:
    """Let the Users group pass through one directory and read its attributes.

    Nothing under the directory inherits the grant, and nothing in it is
    listed.

    Args:
        run: Runs one command as :func:`subprocess_run.run` does.
        directory: The directory.

    Raises:
        OSError: When icacls refuses or cannot run.
    """
    code = icacls(
        run, [directory, "/grant", f"{WINDOWS_ACL_USERS}:{WINDOWS_ACL_PASS_THROUGH}"]
    )
    if code != 0:
        raise OSError(f"icacls exited {code}")


def leave_to_system(run, path: str) -> None:
    """Leave one file to SYSTEM and the administrators alone, nothing inherited.

    Args:
        run: Runs one command as :func:`subprocess_run.run` does.
        path: The file.

    Raises:
        OSError: When icacls refuses or cannot run.
    """
    code = icacls(
        run,
        [
            path,
            "/inheritance:r",
            "/grant:r",
            f"{WINDOWS_ACL_SYSTEM}:F",
            f"{WINDOWS_ACL_ADMINISTRATORS}:F",
        ],
    )
    if code != 0:
        raise OSError(f"icacls refused {path}")
