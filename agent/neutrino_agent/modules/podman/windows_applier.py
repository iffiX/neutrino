"""Containers on Windows: what a Podman machine on WSL needs of the computer.

The install turns on the two Windows features WSL 2 needs with dism,
installs Microsoft's WSL msi unless the WSL the manifest pins or a newer one
is installed, and installs Podman's msi for every account. A dism or an msi
exit 3010 writes the reboot mark, the boot time of the boot that owes the
restart, which holds the module installing until Windows has restarted. WSL
holds the machine's size: its processors and memory in the account's
``.wslconfig``, its disk as the VHDX ``wsl --manage`` resizes. Every ``wsl``
command and the ``.wslconfig`` write run as the account, since WSL refuses
SYSTEM.

Not pure: runs dism, msiexec and wsl, reads the registry, writes the
account's ``.wslconfig``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ctypes
import ntpath
import os
import struct
import subprocess
import time
import uuid

from neutrino_agent.constants import (
    AGENT_UPDATE_MSI_REBOOT_CODE,
    AGENT_WINDOWS_PROGRAM_FILES_DEFAULT,
    AGENT_WINDOWS_SYSTEM_ROOT_DEFAULT,
)
from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.podman.constants import (
    PODMAN_GIB,
    PODMAN_MACHINE_DETAIL_CHARS,
    PODMAN_MACHINE_NAME,
    PODMAN_MACHINE_PROVIDER_WSL,
    PODMAN_MODULE_NAME,
    PODMAN_WINDOWS_BINARY_PARTS,
    PODMAN_WINDOWS_BOOT_SLACK_S,
    PODMAN_WINDOWS_DISK_PARTS,
    PODMAN_WINDOWS_DISM_TIMEOUT_S,
    PODMAN_WINDOWS_FEATURES,
    PODMAN_WINDOWS_OTHER_VERSION_CODE,
    PODMAN_WINDOWS_PODMAN_PRODUCT,
    PODMAN_WINDOWS_PODMAN_PROPERTIES,
    PODMAN_WINDOWS_REBOOT_MARK,
    PODMAN_WINDOWS_RESTART_KEY,
    PODMAN_WINDOWS_UNINSTALL_KEY,
    PODMAN_WINDOWS_UNKNOWN_PRODUCT_CODE,
    PODMAN_WINDOWS_WSL_ARTIFACT,
    PODMAN_WINDOWS_WSL_PRODUCT,
    PODMAN_WINDOWS_WSL_TIMEOUT_S,
    PODMAN_WINDOWS_WSL_VERSION,
    PODMAN_WINDOWS_WSLCONFIG,
    PODMAN_WINDOWS_WSLCONFIG_SECTION,
)
from neutrino_agent.modules.podman.machine_runner import PodmanSystemApplier
from neutrino_agent.modules.shared import installers
from neutrino_agent.modules.shared.subprocess_run import command_detail
from neutrino_agent.modules.shared.subprocess_run import run as run_command
from neutrino_agent.platforms import win32

try:
    import winreg
except ImportError:  # Only Windows has the registry module.
    winreg = None

# The VHDX format: the file's signature, the region table 192 KiB in, the
# metadata region and its table, and the item that holds the disk's
# virtual size in bytes.
_VHDX_SIGNATURE = b"vhdxfile"
_VHDX_REGION_TABLE_OFFSET = 192 * 1024
_VHDX_REGION_SIGNATURE = b"regi"
_VHDX_METADATA_REGION = uuid.UUID("8B7CA206-4790-4B9A-B8FE-575F050F886E").bytes_le
_VHDX_METADATA_SIGNATURE = b"metadata"
_VHDX_VIRTUAL_DISK_SIZE = uuid.UUID("2FA54224-CD1B-4876-B211-5DBED83BF4B8").bytes_le
_VHDX_TABLE_BYTES = 64 * 1024
_VHDX_ENTRY_BYTES = 32


def version_numbers(text: str) -> tuple:
    """A dotted version as numbers, such as ``(3, 0, 3, 0)`` for ``3.0.3.0``.

    Args:
        text: The version.

    Returns:
        Each part's leading digits as a number, 0 for a part with none.
    """
    numbers = []
    for part in str(text or "").strip().split("."):
        digits = ""
        for character in part:
            if not character.isdigit():
                break
            digits += character
        numbers.append(int(digits or 0))
    return tuple(numbers)


def merged_wslconfig(text: str, *, processors: int, memory_gib: int) -> str:
    """A ``.wslconfig`` with ``processors`` and ``memory`` set under ``[wsl2]``.

    Every other line stays as it is, comments and the other keys of
    ``[wsl2]`` among them. A missing section is added at the end; a missing
    key goes after the last line of its section.

    Args:
        text: The file's text, empty when there is none.
        processors: The processors WSL gives its machine.
        memory_gib: The memory WSL gives it, in GiB.

    Returns:
        The file's new text, in the file's own line ends, CRLF for a new
        file.
    """
    newline = "\n" if text and "\r\n" not in text else "\r\n"
    wanted = {
        "processors": f"processors={processors}",
        "memory": f"memory={memory_gib}GB",
    }
    lines = []
    seen = set()
    section = ""
    section_end = -1
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        stripped = body.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            lines.append(line)
            if section == PODMAN_WINDOWS_WSLCONFIG_SECTION:
                section_end = len(lines)
            continue
        if section != PODMAN_WINDOWS_WSLCONFIG_SECTION:
            lines.append(line)
            continue
        key = ""
        if "=" in stripped and not stripped.startswith(("#", ";")):
            key = stripped.partition("=")[0].strip().lower()
        if key in wanted:
            seen.add(key)
            lines.append(wanted[key] + (line[len(body) :] or newline))
        else:
            lines.append(line)
        if stripped:
            section_end = len(lines)
    missing = [wanted[key] + newline for key in wanted if key not in seen]
    if not missing:
        return "".join(lines)
    if section_end < 0:
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.append(f"[{PODMAN_WINDOWS_WSLCONFIG_SECTION}]{newline}")
        lines.extend(missing)
    else:
        if not lines[section_end - 1].endswith(("\r", "\n")):
            lines[section_end - 1] += newline
        lines[section_end:section_end] = missing
    return "".join(lines)


def vhdx_virtual_size(stream) -> int:
    """The virtual size of a VHDX disk, read from its metadata.

    Args:
        stream: The disk file, open for reading in binary.

    Returns:
        The size in bytes the disk offers its machine.

    Raises:
        ValueError: When the file is not a VHDX disk or names no size.
        OSError: When the file cannot be read.
    """
    stream.seek(0)
    if stream.read(len(_VHDX_SIGNATURE)) != _VHDX_SIGNATURE:
        raise ValueError("not a VHDX disk")
    stream.seek(_VHDX_REGION_TABLE_OFFSET)
    regions = stream.read(_VHDX_TABLE_BYTES)
    try:
        signature, _checksum, count, _reserved = struct.unpack_from("<4sIII", regions)
        if signature != _VHDX_REGION_SIGNATURE:
            raise ValueError("the VHDX disk has no region table")
        for index in range(count):
            region, metadata_at, _length, _required = struct.unpack_from(
                "<16sQII", regions, 16 + _VHDX_ENTRY_BYTES * index
            )
            if region == _VHDX_METADATA_REGION:
                break
        else:
            raise ValueError("the VHDX disk has no metadata region")
        stream.seek(metadata_at)
        metadata = stream.read(_VHDX_TABLE_BYTES)
        signature, _reserved, count = struct.unpack_from("<8sHH", metadata)
        if signature != _VHDX_METADATA_SIGNATURE:
            raise ValueError("the VHDX disk has no metadata table")
        for index in range(count):
            item, item_at, _length, _flags, _reserved = struct.unpack_from(
                "<16sIIII", metadata, _VHDX_ENTRY_BYTES * (index + 1)
            )
            if item == _VHDX_VIRTUAL_DISK_SIZE:
                stream.seek(metadata_at + item_at)
                return struct.unpack("<Q", stream.read(8))[0]
    except struct.error as error:
        raise ValueError(f"the VHDX disk is cut short: {error}") from error
    raise ValueError("the VHDX disk names no virtual size")


def wsl_script(wsl: str, arguments: list) -> str:
    """The PowerShell line that runs ``wsl.exe`` with its options as bare words.

    wsl.exe takes a quoted option for a command to run in Linux, and
    PowerShell passes a word with no space in it unquoted. ``WSL_UTF8``
    makes wsl.exe write UTF-8 in place of UTF-16.

    Args:
        wsl: wsl.exe's path.
        arguments: Its arguments, none with a space in it.

    Returns:
        The line, which exits with wsl.exe's exit code.
    """
    words = " ".join(installers.powershell_quote(word) for word in [wsl, *arguments])
    return f"$env:WSL_UTF8 = '1'; & {words}; exit $LASTEXITCODE"


def installed_products() -> list:
    """The products Windows Installer lists under the machine's Uninstall key.

    Returns:
        ``[{"code", "name", "version"}]``, one per Windows Installer product,
        ``code`` its product code; empty off Windows or when the key cannot
        be read.
    """
    if winreg is None:
        return []
    access = winreg.KEY_READ | win32.KEY_WOW64_64KEY
    try:
        root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, PODMAN_WINDOWS_UNINSTALL_KEY, 0, access
        )
    except OSError:
        return []
    products = []
    with root:
        index = 0
        while True:
            try:
                code = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, code, 0, access) as key:
                    values = {
                        name: _registry_value(key, name)
                        for name in (
                            "DisplayName",
                            "DisplayVersion",
                            "WindowsInstaller",
                        )
                    }
            except OSError:
                continue
            if values["WindowsInstaller"] != 1:
                continue
            products.append(
                {
                    "code": code,
                    "name": str(values["DisplayName"] or ""),
                    "version": str(values["DisplayVersion"] or ""),
                }
            )
    return products


def is_restart_key_present() -> bool:
    """Whether Windows' servicing holds its key for a restart it waits for.

    Returns:
        True while ``Component Based Servicing\\RebootPending`` exists.
    """
    if winreg is None:
        return False
    try:
        winreg.CloseKey(
            winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                PODMAN_WINDOWS_RESTART_KEY,
                0,
                winreg.KEY_READ | win32.KEY_WOW64_64KEY,
            )
        )
    except OSError:
        return False
    return True


def boot_time() -> float:
    """When this boot began, in seconds of the wall clock.

    Returns:
        The time now less the milliseconds ``GetTickCount64`` counts since
        the boot.

    Raises:
        OSError: Off Windows.
    """
    return time.time() - win32.libraries().kernel32.GetTickCount64() / 1000.0


def memory_bytes() -> int:
    """The computer's memory, in bytes.

    Returns:
        ``ullTotalPhys`` as ``GlobalMemoryStatusEx`` fills it in; 0 when it
        refuses.

    Raises:
        OSError: Off Windows.
    """
    status = win32.MemoryStatusEx()
    status.dwLength = ctypes.sizeof(win32.MemoryStatusEx)
    if not win32.libraries().kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.ullTotalPhys)


def _registry_value(key, name: str):
    """One value of an open key, None when it has none."""
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value


def _merge_wslconfig(path: str, processors: int, memory_gib: int) -> bool:
    """Write the two keys into one ``.wslconfig``, run as its account.

    Returns:
        Whether the file changed.
    """
    try:
        with open(path, "rb") as stream:
            data = stream.read()
    except FileNotFoundError:
        data = b""
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    text = data[len(bom) :].decode("utf-8", "surrogateescape")
    merged = merged_wslconfig(text, processors=processors, memory_gib=memory_gib)
    if merged == text:
        return False
    with open(path, "wb") as stream:
        stream.write(bom + merged.encode("utf-8", "surrogateescape"))
    return True


class PodmanWindowsApplier(PodmanSystemApplier):
    """The computer's part of a Podman machine on Windows, on WSL 2."""

    provider = PODMAN_MACHINE_PROVIDER_WSL

    def __init__(
        self,
        *,
        platform,
        log=print,
        run=run_command,
        install_msi=installers.install_msi,
        uninstall_msi=installers.uninstall_msi,
        read_products=installed_products,
        has_restart_key=is_restart_key_present,
        read_boot_time=boot_time,
        read_memory_bytes=memory_bytes,
        join=ntpath.join,
    ):
        """
        Args:
            platform: The computer's platform: its state root, the accounts'
                homes, and acting as an account.
            log: Called with each progress line.
            run: Runs one command as :func:`subprocess_run.run` does, dism's.
            install_msi: Installs one msi as :func:`installers.install_msi`.
            uninstall_msi: Uninstalls one product as
                :func:`installers.uninstall_msi`.
            read_products: Lists the installed products as
                :func:`installed_products` does.
            has_restart_key: Whether servicing waits for a restart, as
                :func:`is_restart_key_present` says.
            read_boot_time: When this boot began, as :func:`boot_time` says.
            read_memory_bytes: The computer's memory, as
                :func:`memory_bytes` says.
            join: Joins path parts, Windows' way unless told otherwise.
        """
        self._platform = platform
        self._log = log
        self._run = run
        self._install_msi = install_msi
        self._uninstall_msi = uninstall_msi
        self._read_products = read_products
        self._has_restart_key = has_restart_key
        self._read_boot_time = read_boot_time
        self._read_memory_bytes = read_memory_bytes
        self._join = join
        program_files = (
            os.environ.get("ProgramFiles") or AGENT_WINDOWS_PROGRAM_FILES_DEFAULT
        )
        system32 = ntpath.join(
            os.environ.get("SystemRoot") or AGENT_WINDOWS_SYSTEM_ROOT_DEFAULT,
            "System32",
        )
        self.binary = ntpath.join(program_files, *PODMAN_WINDOWS_BINARY_PARTS)
        self._dism = ntpath.join(system32, "dism.exe")
        self._wsl = ntpath.join(system32, "wsl.exe")
        self._module_dir = join(platform.agent_var_dir(), PODMAN_MODULE_NAME)
        self._mark_path = join(self._module_dir, PODMAN_WINDOWS_REBOOT_MARK)
        # The features are turned on once per install, before its first msi.
        self._has_features = False

    def install_artifact(self, artifact: dict, path: str) -> None:
        """Turn on the Windows features once, then install the WSL or Podman msi.

        Args:
            artifact: ``{name, kind, digest, directory}``.
            path: The kept msi.

        Raises:
            ModuleApplyError: ``windows_feature_failed {feature, exit_code}``
                when dism refuses a feature; ``podman_install_failed
                {artifact, exit_code}`` when an msi fails; ``install_failed``
                for an artifact that is not an msi.
        """
        name = str(artifact.get("name", "") or "")
        if artifact.get("kind") != "msi":
            raise ModuleApplyError(
                "install_failed", {"detail": f"artifact {name!r} is not an msi"}
            )
        if not self._has_features:
            for feature in PODMAN_WINDOWS_FEATURES:
                self._enable_feature(feature)
            self._has_features = True
        is_wsl = name == PODMAN_WINDOWS_WSL_ARTIFACT
        if is_wsl:
            installed = self._installed_wsl()
            if installed:
                self._log(f"podman: WSL {installed} is installed; its msi is not run")
                return
        properties = () if is_wsl else PODMAN_WINDOWS_PODMAN_PROPERTIES
        log_path = ntpath.splitext(path)[0] + ".log"
        try:
            is_owed = self._install_msi(path, log_path=log_path, properties=properties)
        except InstallError as error:
            if is_wsl and error.exit_code == PODMAN_WINDOWS_OTHER_VERSION_CODE:
                self._log("podman: another WSL is installed; its msi is not run")
                return
            exit_code = -1 if error.exit_code is None else error.exit_code
            raise ModuleApplyError(
                "podman_install_failed", {"artifact": name, "exit_code": exit_code}
            ) from error
        self._log(f"podman: installed {name}")
        if is_owed:
            self._mark_restart(f"the {name} msi")

    def is_reboot_pending(self) -> bool:
        """Whether the computer still owes the restart an install step asked for.

        The mark's boot time is compared with this boot's; once the boot
        changed and servicing waits for no restart, the mark is deleted.

        Returns:
            True while the reboot mark holds this boot, or holds an earlier
            one while servicing still waits for a restart.
        """
        try:
            with open(self._mark_path, "r", encoding="utf-8") as stream:
                marked = float(stream.read().strip())
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            marked = None
        if marked is not None:
            if self._read_boot_time() - marked <= PODMAN_WINDOWS_BOOT_SLACK_S:
                return True
            if self._has_restart_key():
                return True
        self._forget_restart()
        return False

    def uninstall(self) -> None:
        """Uninstall Podman's msi and forget the reboot mark; WSL and the features stay.

        Raises:
            ModuleApplyError: ``uninstall_failed`` when msiexec fails.
        """
        log_path = self._join(self._module_dir, "uninstall.log")
        for product in self._read_products():
            if product["name"] != PODMAN_WINDOWS_PODMAN_PRODUCT:
                continue
            try:
                self._uninstall_msi(product["code"], log_path=log_path)
            except InstallError as error:
                if error.exit_code == PODMAN_WINDOWS_UNKNOWN_PRODUCT_CODE:
                    continue
                raise ModuleApplyError(
                    "uninstall_failed",
                    {"detail": str(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
                ) from error
            self._log(f"podman: uninstalled {product['name']} {product['version']}")
        self._forget_restart()

    def host_facts(self) -> tuple:
        """The computer's logical processors and its memory in GiB.

        Returns:
            ``(cpus, memory_gib)``, the memory rounded to whole GiB; 0 for
            what cannot be read.
        """
        try:
            total = self._read_memory_bytes()
        except OSError:
            total = 0
        return (os.cpu_count() or 0, round(total / PODMAN_GIB))

    def disk_gib(self, machine) -> int:
        """The virtual size of the machine's WSL disk in GiB.

        Args:
            machine: The machine.

        Returns:
            The size, rounded to whole GiB; 0 when the disk cannot be read.
        """
        try:
            path = self._join(
                self._platform.account_home(machine.account), *PODMAN_WINDOWS_DISK_PARTS
            )
            with open(path, "rb") as stream:
                return round(vhdx_virtual_size(stream) / PODMAN_GIB)
        except (KeyError, OSError, ValueError):
            return 0

    def halt(self, machine) -> None:
        """Stop every WSL system of the account, so WSL reads its new size.

        Args:
            machine: The machine.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when ``wsl --shutdown``
                fails; ``credential_invalid`` when Windows refuses the login.
        """
        self._wsl_as(machine, ["--shutdown"])

    def terminate(self, machine) -> None:
        """End the stopped machine's WSL system, as the account, so its next
        start takes WSL's NAT network and resolver anew.

        Args:
            machine: The machine.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when ``wsl --terminate``
                fails; ``credential_invalid`` when Windows refuses the login.
        """
        self._wsl_as(machine, ["--terminate", PODMAN_MACHINE_NAME])

    def write_resources(self, machine, *, cpus: int, memory_gib: int) -> None:
        """Write the processors and the memory into the account's ``.wslconfig``, as the account.

        Args:
            machine: The machine.
            cpus: Its processors.
            memory_gib: Its memory in GiB.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when the file cannot be
                written; ``credential_invalid`` when Windows refuses the
                login.
        """
        try:
            path = self._join(
                self._platform.account_home(machine.account), PODMAN_WINDOWS_WSLCONFIG
            )
            if machine.as_account(_merge_wslconfig, path, cpus, memory_gib):
                self._log(
                    f"podman: {path} gives WSL {cpus} processors and {memory_gib} GB"
                )
        except (KeyError, OSError) as error:
            raise ModuleApplyError(
                "machine_set_failed",
                {"detail": str(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error

    def resize_disk(self, machine, *, disk_gib: int) -> None:
        """Stop every WSL system of the account, then give the machine's disk a new size, as the account.

        WSL holds the disk until its virtual machine stops, after an init
        too, so the resize follows a ``wsl --shutdown``.

        Args:
            machine: The machine.
            disk_gib: The size in GiB.

        Raises:
            ModuleApplyError: ``machine_set_failed`` when WSL refuses the
                size; ``credential_invalid`` when Windows refuses the login.
        """
        self._wsl_as(machine, ["--shutdown"])
        self._wsl_as(
            machine, ["--manage", PODMAN_MACHINE_NAME, "--resize", f"{disk_gib}GB"]
        )
        self._log(f"podman: the disk of {machine.account}'s machine is {disk_gib} GB")

    def _enable_feature(self, feature: str) -> None:
        """Turn on one Windows feature with dism, marking a restart it owes.

        Raises:
            ModuleApplyError: ``windows_feature_failed {feature, exit_code}``
                for an exit other than 0 and 3010, -1 when dism did not run.
        """
        command = [
            self._dism,
            "/English",
            "/Online",
            "/Enable-Feature",
            f"/FeatureName:{feature}",
            "/All",
            "/NoRestart",
        ]
        try:
            exit_code = self._run(
                command, is_checked=False, timeout_s=PODMAN_WINDOWS_DISM_TIMEOUT_S
            ).exit_code
        except (OSError, subprocess.SubprocessError):
            exit_code = -1
        if exit_code == AGENT_UPDATE_MSI_REBOOT_CODE:
            self._mark_restart(feature)
        elif exit_code != 0:
            raise ModuleApplyError(
                "windows_feature_failed", {"feature": feature, "exit_code": exit_code}
            )
        else:
            self._log(f"podman: {feature} is on")

    def _installed_wsl(self) -> str:
        """The installed WSL's version when it is the pinned one or newer, else empty."""
        pinned = version_numbers(PODMAN_WINDOWS_WSL_VERSION)
        for product in self._read_products():
            if product["name"] != PODMAN_WINDOWS_WSL_PRODUCT:
                continue
            if version_numbers(product["version"]) >= pinned:
                return product["version"]
        return ""

    def _mark_restart(self, step: str) -> None:
        """Write the reboot mark, this boot's time, for a step that owes a restart."""
        os.makedirs(self._module_dir, exist_ok=True)
        with open(self._mark_path, "w", encoding="utf-8") as stream:
            stream.write(f"{self._read_boot_time():.0f}\n")
        self._log(f"podman: {step} needs Windows to restart")

    def _forget_restart(self) -> None:
        """Delete the reboot mark, when there is one."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._mark_path)

    def _wsl_as(self, machine, arguments: list) -> None:
        """Run ``wsl.exe`` as the machine's account, through PowerShell.

        Raises:
            ModuleApplyError: ``machine_set_failed`` with WSL's own words when
                it exits non-zero or cannot start; ``credential_invalid``
                when Windows refuses the login.
        """
        try:
            done = machine.run_as_account(
                installers.powershell_command(wsl_script(self._wsl, arguments)),
                timeout_s=PODMAN_WINDOWS_WSL_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "machine_set_failed",
                {"detail": command_detail(error)[:PODMAN_MACHINE_DETAIL_CHARS]},
            ) from error
        if done.returncode != 0:
            said = f"{done.stdout or ''}{done.stderr or ''}".strip()
            detail = said or f"wsl {arguments[0]} exited {done.returncode}"
            raise ModuleApplyError(
                "machine_set_failed", {"detail": detail[-PODMAN_MACHINE_DETAIL_CHARS:]}
            )
