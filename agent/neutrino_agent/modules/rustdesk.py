"""RustDesk as a module, and the mechanics of driving it.

The Linux agent packages carry the host at
:data:`~neutrino_agent.constants.AGENT_RUSTDESK_BINARY_PATH`, so a machine
that has the agent has RustDesk and nothing is fetched onto it.
``rdp/host.py`` decides when a machine shares its desktop; everything here
is what RustDesk itself is and how it is driven.

**No rendezvous server.** ``custom-rendezvous-server`` and ``relay-server``
are written empty and ``direct-server`` is on, so a peer is reached by
address on :data:`RUSTDESK_DIRECT_PORT` and nothing routes through a third
party. Configuration is written into ``RustDesk2.toml`` at every path the
running service and the desktop session read, never through ``--config``.

**The permanent password can only go on argv.** RustDesk 1.4.9 accepts it
as ``rustdesk --password <value>`` and offers no standard input; the stored
form is salted, so no file write can set it either. The call is made as
short-lived as it can be and is the one place a secret is on a command
line.

Not pure: writes configuration and drives services.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import subprocess
import time

from neutrino_agent.constants import AGENT_RUSTDESK_BINARY_PATH
from neutrino_agent.modules.installers import InstallError

RUSTDESK_TIMEOUT_S = 60
# Long enough for a service to come up on a slow machine, short enough that
# a share flow never looks hung.
RUSTDESK_SERVICE_TIMEOUT_S = 120

# How long the password call keeps being made while the service is still
# coming up, and how often. The unit is `Type=simple`, so the platform's
# service control returns as soon as the process is forked and the socket
# the password travels over accepts about half a second later.
RUSTDESK_PASSWORD_READY_TIMEOUT_S = 15
RUSTDESK_PASSWORD_RETRY_S = 0.25

# The port a direct connection lands on. RustDesk dials a bare address at
# its own relay port plus one, so a peer typed as an address reaches this
# without a rendezvous server; ``direct-access-port`` is set to match.
RUSTDESK_DIRECT_PORT = 21118

# What the service and the desktop session read. Written to both, because
# the service answering a connection and the session showing it are
# different processes with different homes.
RUSTDESK_CONFIG_NAME = "RustDesk2.toml"
RUSTDESK_ROOT_CONFIG = "/root/.config/rustdesk"
RUSTDESK_ACCOUNT_RELATIVE = ".config/rustdesk"

# Where the binary is: the agent's own build first, then a package's.
RUSTDESK_BINARY_PATHS = (
    AGENT_RUSTDESK_BINARY_PATH,
    "/usr/bin/rustdesk",
    "/usr/local/bin/rustdesk",
)

RUSTDESK_ACTION_START = "start"
RUSTDESK_ACTION_STOP = "stop"
RUSTDESK_ACTION_RESTART = "restart"

RUSTDESK_UNIT = "rustdesk"

# What every machine gets when the agent starts: no rendezvous, no relay,
# the direct port pinned. Connections under a hub are dialed by
# address on the LAN; nothing registers with public infrastructure.
# ``direct-server`` is not here — opening the port is the share's decision.
RUSTDESK_BASE_OPTIONS = (
    ("custom-rendezvous-server", ""),
    ("relay-server", ""),
    ("direct-access-port", str(RUSTDESK_DIRECT_PORT)),
    ("allow-auto-update", "N"),
)

# What the share flow writes. Direct mode with a permanent password, and
# every channel this hub does not publish turned off.
RUSTDESK_SHARE_OPTIONS = (
    ("custom-rendezvous-server", ""),
    ("relay-server", ""),
    ("direct-server", "Y"),
    ("direct-access-port", str(RUSTDESK_DIRECT_PORT)),
    ("allow-auto-update", "N"),
    ("verification-method", "use-permanent-password"),
    ("approve-mode", "password"),
    ("enable-file-transfer", "N"),
    ("enable-tunnel", "N"),
    ("enable-audio", "N"),
)

# An id is six to twelve digits: the machines this has run on were issued
# eight, and the bound keeps a longer run of digits from reading as one.
RUSTDESK_ID_PATTERN = re.compile(r"\b(\d{6,12})\b")

# A key = 'value' line of the options table, as RustDesk itself writes it.
RUSTDESK_OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")


def binary_path() -> str:
    """Where RustDesk is on this machine.

    Returns:
        The executable's path, empty when it is not installed.
    """
    for candidate in RUSTDESK_BINARY_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return ""


def read_id() -> str:
    """The id a peer connects to this machine by.

    Returns:
        The id, empty when RustDesk is absent or has not been assigned one.
    """
    binary = binary_path()
    if not binary:
        return ""
    try:
        result = subprocess.run(
            [binary, "--get-id"],
            capture_output=True,
            text=True,
            timeout=RUSTDESK_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    match = RUSTDESK_ID_PATTERN.search(result.stdout or "")
    return match.group(1) if match else ""


def config_paths(account_home: str = "") -> list:
    """Every ``RustDesk2.toml`` this machine reads, most privileged first.

    Args:
        account_home: The home of the account sitting at the machine; empty
            writes only the service's own.

    Returns:
        The paths to write.
    """
    paths = [os.path.join(RUSTDESK_ROOT_CONFIG, RUSTDESK_CONFIG_NAME)]
    if account_home:
        paths.append(
            os.path.join(account_home, RUSTDESK_ACCOUNT_RELATIVE, RUSTDESK_CONFIG_NAME)
        )
    return paths


def render_config(existing: str, options: tuple) -> str:
    """One ``RustDesk2.toml`` with the given options settled into it.

    Everything above the options table is kept as it was — the machine's own
    rendezvous state lives there — and an option RustDesk wrote that this
    does not name is kept too.

    Args:
        existing: The file's current text, empty when there is none.
        options: ``(key, value)`` pairs to set.

    Returns:
        The whole file to write.
    """
    preamble = []
    kept = []
    is_in_options = False
    named = {key for key, _ in options}
    for line in existing.splitlines():
        if line.strip().startswith("[") and line.strip().endswith("]"):
            is_in_options = line.strip() == "[options]"
            if not is_in_options:
                # A table after the options is not one this writes; keeping
                # it would move it above the options it followed.
                break
            continue
        if not is_in_options:
            preamble.append(line)
            continue
        match = RUSTDESK_OPTION_PATTERN.match(line)
        if match is not None and match.group(1) not in named:
            kept.append(line)
    body = "\n".join(line for line in preamble if line.strip())
    lines = [body] if body else []
    lines.append("[options]")
    lines.extend(f"{key} = '{value}'" for key, value in options)
    lines.extend(kept)
    return "\n".join(lines) + "\n"


def write_config(path: str, options: tuple) -> bool:
    """Write one ``RustDesk2.toml``, keeping what it already said and whose
    it was.

    **The owner is part of the file.** A session's copy is written by this
    root daemon but read *and written* by RustDesk running as that person:
    on Wayland it stores the screen-capture permission there
    (``wayland-restore-token``), so a copy left owned by root costs them
    that permission dialog on every single connection. The file keeps the
    owner and mode it had, and a new one under a home is created as that
    home's owner.

    Args:
        path: The file to write.
        options: ``(key, value)`` pairs to set.

    Returns:
        True when the file's text is not what it was.

    Raises:
        InstallError: If the file cannot be written.
    """
    try:
        existing = ""
        kept = _owner_of(path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as stream:
                existing = stream.read()
        rendered = render_config(existing, options)
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        if kept is not None:
            os.chown(temporary, kept[0], kept[1])
            os.chmod(temporary, kept[2])
        os.replace(temporary, path)
    except OSError as error:
        raise InstallError(f"could not write {path}: {error}")
    return rendered != existing


def _owner_of(path: str):
    """Who a config belongs to, so a rewrite does not take it away.

    Args:
        path: The file being written.

    Returns:
        ``(uid, gid, mode)`` to restore, or None where nothing says whose
        the file is. An existing file answers for itself; a new one takes
        its directory's owner, which under a home is that person.
    """
    existing = _stat(path)
    if existing is not None:
        return existing.st_uid, existing.st_gid, existing.st_mode & 0o777
    for parent in (os.path.dirname(path), os.path.dirname(os.path.dirname(path))):
        owner = _stat(parent)
        if owner is not None and owner.st_uid != 0:
            return owner.st_uid, owner.st_gid, 0o644
    return None


def _stat(path: str):
    """One path's stat, or None when it cannot be read."""
    try:
        return os.stat(path)
    except OSError:
        return None


def set_password(password: str) -> None:
    """Set the permanent password a peer connects with.

    RustDesk 1.4.9 takes this only as ``--password <value>``: it reads no
    standard input and stores the password salted, so no file write reaches
    it. The value is on this one argument vector for the length of the call
    and is kept nowhere else on the machine.

    **The call is also the readiness check.** It travels over the service's
    own socket, which starts accepting after the service control has already
    returned, so a call made straight after a restart is refused by the
    socket rather than by RustDesk. Nothing else the binary offers proves
    that socket is up — ``--get-id`` answers out of the configuration file
    with the service stopped — so the call is repeated until it takes.

    Args:
        password: The access password.

    Raises:
        InstallError: If RustDesk is absent, or still refusing when the
            wait runs out.
    """
    binary = binary_path()
    if not binary:
        raise InstallError("RustDesk is not installed")
    deadline = time.monotonic() + RUSTDESK_PASSWORD_READY_TIMEOUT_S
    while True:
        refusal = _password_refusal(binary, password)
        if not refusal:
            return
        if time.monotonic() >= deadline:
            raise InstallError(f"rustdesk refused the password: {refusal}")
        time.sleep(RUSTDESK_PASSWORD_RETRY_S)


def _password_refusal(binary: str, password: str) -> str:
    """Make the password call once.

    Args:
        binary: The RustDesk binary.
        password: The access password.

    Returns:
        Empty when it took, what RustDesk printed when it did not.

    Raises:
        InstallError: If the binary could not be run at all, which no wait
            would fix.
    """
    try:
        result = subprocess.run(
            [binary, "--password", password],
            capture_output=True,
            text=True,
            timeout=RUSTDESK_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"rustdesk --password could not run: {error}")
    # The binary reports a refusal on standard output and still exits zero.
    printed = (result.stdout or "").strip()
    if result.returncode != 0 or (printed and not printed.startswith("Done")):
        return printed or f"exit {result.returncode}"
    return ""


def control_service(action: str) -> None:
    """Start or stop the RustDesk service.

    Args:
        action: ``start`` or ``stop``.

    Raises:
        InstallError: If systemd refuses.
    """
    command = ["systemctl", action, RUSTDESK_UNIT]
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=RUSTDESK_SERVICE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"{command[0]} could not run: {error}")
