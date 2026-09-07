"""RustDesk as a module, and the mechanics of driving it.

The hub's cache fetches the pinned release for this platform and hands the
bytes down; this installs them with the platform's own installer, registers
the service where the package does not, and answers what is on the machine.
The rdp service in ``services/rdp.py`` decides when a machine shares its
desktop; everything here is what RustDesk itself is and how it is driven.

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

Not pure: installs packages, writes configuration and drives services.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import subprocess
import time

from neutrino_agent.modules.base import ModuleRunner
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

# What the service and the desktop session read. Written to every one of
# them, because the service answering a connection and the session showing
# it are different processes with different homes.
RUSTDESK_CONFIG_NAME = "RustDesk2.toml"
RUSTDESK_WINDOWS_SERVICE_PROFILE = (
    "C:\\Windows\\ServiceProfiles\\LocalService\\AppData\\Roaming\\RustDesk\\config"
)
RUSTDESK_WINDOWS_ACCOUNT_RELATIVE = "AppData\\Roaming\\RustDesk\\config"
RUSTDESK_LINUX_ROOT_CONFIG = "/root/.config/rustdesk"
RUSTDESK_LINUX_ACCOUNT_RELATIVE = ".config/rustdesk"
RUSTDESK_DARWIN_ROOT_CONFIG = "/var/root/Library/Preferences/com.carriez.RustDesk"
RUSTDESK_DARWIN_ACCOUNT_RELATIVE = "Library/Preferences/com.carriez.RustDesk"

# Where the binary lands, per platform.
RUSTDESK_BINARY_PATHS = (
    "/usr/bin/rustdesk",
    "/usr/local/bin/rustdesk",
    "C:\\Program Files\\RustDesk\\RustDesk.exe",
    "/Applications/RustDesk.app/Contents/MacOS/RustDesk",
)

RUSTDESK_ACTION_START = "start"
RUSTDESK_ACTION_STOP = "stop"
# Windows drives a service by its own verb pair, keyed on whether the ask
# was to start it.
RUSTDESK_WINDOWS_VERBS = {True: "start", False: "stop"}

RUSTDESK_WINDOWS_SERVICE = "RustDesk"
RUSTDESK_LINUX_UNIT = "rustdesk"
RUSTDESK_DARWIN_DAEMON_LABEL = "com.carriez.RustDesk_service"
RUSTDESK_DARWIN_DAEMON_PLIST = (
    "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist"
)

# What every machine gets the moment the module lands: no rendezvous, no
# relay, the direct port pinned. Connections under a hub are dialed by
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
    if os.name == "nt":
        paths = [os.path.join(RUSTDESK_WINDOWS_SERVICE_PROFILE, RUSTDESK_CONFIG_NAME)]
        if account_home:
            paths.append(
                os.path.join(
                    account_home,
                    RUSTDESK_WINDOWS_ACCOUNT_RELATIVE,
                    RUSTDESK_CONFIG_NAME,
                )
            )
        return paths
    if _is_darwin():
        paths = [os.path.join(RUSTDESK_DARWIN_ROOT_CONFIG, RUSTDESK_CONFIG_NAME)]
        if account_home:
            paths.append(
                os.path.join(
                    account_home, RUSTDESK_DARWIN_ACCOUNT_RELATIVE, RUSTDESK_CONFIG_NAME
                )
            )
        return paths
    paths = [os.path.join(RUSTDESK_LINUX_ROOT_CONFIG, RUSTDESK_CONFIG_NAME)]
    if account_home:
        paths.append(
            os.path.join(
                account_home, RUSTDESK_LINUX_ACCOUNT_RELATIVE, RUSTDESK_CONFIG_NAME
            )
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


def write_config(path: str, options: tuple) -> None:
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

    Raises:
        InstallError: If the file cannot be written.
    """
    try:
        existing = ""
        kept = _owner_of(path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as stream:
                existing = stream.read()
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(render_config(existing, options))
        if kept is not None:
            os.chown(temporary, kept[0], kept[1])
            os.chmod(temporary, kept[2])
        os.replace(temporary, path)
    except OSError as error:
        raise InstallError(f"could not write {path}: {error}")


def _owner_of(path: str):
    """Who a config belongs to, so a rewrite does not take it away.

    Args:
        path: The file being written.

    Returns:
        ``(uid, gid, mode)`` to restore, or None where this platform has no
        such notion or nothing says whose the file is. An existing file
        answers for itself; a new one takes its directory's owner, which
        under a home is that person.
    """
    if os.name == "nt":
        return None
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
    """Start or stop the RustDesk service, the way this platform does.

    Args:
        action: ``start`` or ``stop``.

    Raises:
        InstallError: If the platform's own service control refuses.
    """
    is_start = action == RUSTDESK_ACTION_START
    if os.name == "nt":
        command = ["net", RUSTDESK_WINDOWS_VERBS[is_start], RUSTDESK_WINDOWS_SERVICE]
    elif _is_darwin():
        if is_start:
            command = ["launchctl", "bootstrap", "system", RUSTDESK_DARWIN_DAEMON_PLIST]
        else:
            command = ["launchctl", "bootout", f"system/{RUSTDESK_DARWIN_DAEMON_LABEL}"]
    else:
        command = ["systemctl", action, RUSTDESK_LINUX_UNIT]
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=RUSTDESK_SERVICE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"{command[0]} could not run: {error}")


def _is_darwin() -> bool:
    """Whether this machine is macOS."""
    return os.uname().sysname == "Darwin" if hasattr(os, "uname") else False


class RustdeskModuleRunner(ModuleRunner):
    """Puts RustDesk on this machine, takes it off, and reads its id."""

    kind = "rustdesk"

    def verify(self, resolved: dict) -> bool:
        """Whether RustDesk is on this machine.

        The manifest's own check for this platform decides, and its exit
        status is the whole answer — a check that cannot be run reads as
        absent rather than as installed.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            True when it is installed.
        """
        command = str(resolved.get("verify", ""))
        if not command:
            return bool(binary_path())
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, timeout=RUSTDESK_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def details(self, resolved: dict) -> dict:
        """What the surfaces show beside the row.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"rustdesk_id"}`` when an id can be read, empty otherwise.
        """
        identifier = read_id()
        return {"rustdesk_id": identifier} if identifier else {}

    def install(self, resolved: dict, package_path: str) -> None:
        """Install the package the hub handed down, and register the service.

        The deb and the rpm ship their own unit and the dmg's app carries
        its plists, so only Windows needs the binary asked to register
        itself.

        Args:
            resolved: The module as the hub resolved it.
            package_path: The package on local disk.

        Raises:
            InstallError: If the platform's installer refuses.
            PlatformUnsupportedError: If this platform installs nothing.
        """
        entry = resolved.get("entry") or {}
        self._platform.install_package(
            package_path,
            package_kind=str(entry.get("package_kind", "")),
            entry=entry,
        )
        self._register_service()
        self._write_baseline()

    def uninstall(self, resolved: dict) -> None:
        """Take RustDesk off this machine.

        Args:
            resolved: The module as the hub resolved it.

        Raises:
            InstallError: If the uninstall refuses.
            PlatformUnsupportedError: If this platform removes nothing.
        """
        entry = resolved.get("entry") or {}
        command = str(entry.get("uninstall", ""))
        if not command:
            return
        self._platform.uninstall_package(command)

    def _write_baseline(self) -> None:
        """Point the service's own configuration at the LAN and nothing else.

        Best effort beside an install that already succeeded: a machine that
        cannot take the write still verifies installed, and the share writes
        the full set again anyway.
        """
        for path in config_paths(""):
            try:
                write_config(path, RUSTDESK_BASE_OPTIONS)
            except InstallError as error:
                self._log(f"rustdesk: {error}")

    def _register_service(self) -> None:
        """Make RustDesk answer at boot, where its package does not.

        A registration that does not take is logged and not raised: the
        software is installed either way, and the module's verify is what
        reports the truth.

        No pipe is handed to it. Registering leaves a service behind that
        outlives the call, and a service that inherited a captured pipe holds
        it open for as long as it runs — the read never ends and the timeout
        never bounds it. The exit status is the whole answer here.
        """
        binary = binary_path()
        if not binary:
            return
        if os.name == "nt":
            command = [binary, "--install-service"]
        elif _is_darwin():
            if not os.path.isfile(RUSTDESK_DARWIN_DAEMON_PLIST):
                self._log(
                    "rustdesk: the service plists are not installed; "
                    "open RustDesk once on this machine to install them"
                )
                return
            command = ["launchctl", "bootstrap", "system", RUSTDESK_DARWIN_DAEMON_PLIST]
        else:
            command = ["systemctl", "enable", "--now", RUSTDESK_LINUX_UNIT]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=RUSTDESK_SERVICE_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            self._log(f"rustdesk: {command[0]} could not run: {error}")
            return
        if result.returncode != 0:
            self._log(f"rustdesk: {command[0]} exited {result.returncode}")
