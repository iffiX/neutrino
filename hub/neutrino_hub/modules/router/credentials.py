"""Reading the wireless networks this machine already knew.

A box that has been on somebody's desk has joined their Wi-Fi, and the key is
already on the disk — in a NetworkManager keyfile, in iwd's store, or in a
`wpa_supplicant.conf` that is already the format we want. Reading them means
the hub can drive the radio without asking for a passphrase the machine has
held all along.

**What is read must be a subset of the truth.** Missing a network is allowed
and costs one prompt; importing one wrongly is not, because a wrong key is a
radio that fails to associate every time the network comes into range, and
nobody looking at it would think to suspect the import. Every parsing decision
here goes that way: a format that is not understood is skipped, a key
management that is not certainly PSK or SAE is skipped, and a file that does
not parse is not an error.

**Read, never written.** Nothing here edits, moves or deletes another
manager's file.

A key that cannot be read is recorded as a network with no secret rather than
skipped: the network is still one somebody joined, saying "this is known, its
passphrase is somewhere I cannot see" is more use than saying nothing, and an
entry with no secret can never reach the supplicant.

Not pure: reads files outside the hub's own roots.
"""

import configparser
import re
from pathlib import Path

from neutrino_hub.modules.router.connections import RouterConnection
from neutrino_hub.modules.router.constants import (
    ROUTER_KEY_MGMT_NONE,
    ROUTER_KEY_MGMT_PSK,
    ROUTER_KEY_MGMT_SAE,
    ROUTER_SOURCE_INHERITED,
)

# --- config ---
# Where each manager keeps what it was told. All read-only.
#
# NetworkManager reads three directories and so does this: `/etc` for what
# somebody configured, `/run` for what something generated this boot, and
# `/usr/lib` for what a vendor shipped.
CREDENTIAL_NM_DIRS = (
    Path("/etc/NetworkManager/system-connections"),
    Path("/run/NetworkManager/system-connections"),
    Path("/usr/lib/NetworkManager/system-connections"),
)
CREDENTIAL_IWD_DIR = Path("/var/lib/iwd")
CREDENTIAL_WPA_DIR = Path("/etc/wpa_supplicant")
# netplan keeps the passphrase in its own YAML and renders it here, in
# supplicant format, which is why reading it needs no YAML parser. The
# rendered file is what a running machine has.
CREDENTIAL_NETPLAN_DIR = Path("/run/netplan")

CREDENTIAL_MANAGER_NM = "networkmanager"
CREDENTIAL_MANAGER_IWD = "iwd"
CREDENTIAL_MANAGER_WPA = "wpa_supplicant"
CREDENTIAL_MANAGER_NETPLAN = "netplan"

# NetworkManager writes where the passphrase really is into `psk-flags`. 0 is
# the file itself, which is what `nmcli` and netplan produce. 1 is agent-owned
# — it lives in the desktop's keyring and the file holds none — and the rest
# mean not-saved or always-ask. Only 0 carries something to read.
CREDENTIAL_NM_PSK_IN_FILE = "0"
CREDENTIAL_NM_WIFI_TYPES = ("wifi", "802-11-wireless")

# iwd names each file `<ssid>.<security>` and stores an open network as
# `.open`, so the suffix says how to authenticate without reading the file.
CREDENTIAL_IWD_PSK_SUFFIX = ".psk"
CREDENTIAL_IWD_OPEN_SUFFIX = ".open"

# What key managements the hub can carry over. An enterprise network needs a
# certificate and an identity; importing its SSID with no way to authenticate
# would put a network in the list that can never be joined.
CREDENTIAL_PSK_MANAGEMENTS = ("wpa-psk", "wpa-psk-sha256", "sae")

# How wpa_supplicant marks a printf-escaped string. netplan writes every SSID
# this way, and reading the prefix as part of the name gets the network wrong.
SUPPLICANT_PRINTF_PREFIX = 'P"'


class RouterCredentialReader:
    """Reads the wireless networks another manager on this machine holds."""

    def __init__(
        self,
        *,
        nm_dirs: tuple | None = None,
        iwd_dir: Path | None = None,
        wpa_dir: Path | None = None,
        netplan_dir: Path | None = None,
    ):
        """
        Args:
            nm_dirs: Where NetworkManager's keyfiles are. The real locations
                unless a test says otherwise.
            iwd_dir: Where iwd's store is.
            wpa_dir: Where a standalone `wpa_supplicant.conf` is.
            netplan_dir: Where netplan renders what it generated.
        """
        self._nm_dirs = nm_dirs if nm_dirs is not None else CREDENTIAL_NM_DIRS
        self._iwd_dir = iwd_dir if iwd_dir is not None else CREDENTIAL_IWD_DIR
        self._wpa_dir = wpa_dir if wpa_dir is not None else CREDENTIAL_WPA_DIR
        self._netplan_dir = (
            netplan_dir if netplan_dir is not None else CREDENTIAL_NETPLAN_DIR
        )

    def read_all(self) -> list[RouterConnection]:
        """Every network this machine already knew, from every store.

        Returns:
            One entry per network name. Where two managers hold the same SSID,
            the one that carries a key wins — a machine that moved from
            NetworkManager to iwd may have a name in both and a passphrase in
            only one.
        """
        found: dict[str, RouterConnection] = {}
        for connection in (
            self._read_networkmanager()
            + self._read_iwd()
            + self._read_supplicant_files(self._wpa_dir, CREDENTIAL_MANAGER_WPA)
            + self._read_supplicant_files(self._netplan_dir, CREDENTIAL_MANAGER_NETPLAN)
        ):
            existing = found.get(connection.ssid)
            if existing is None or (connection.has_secret and not existing.has_secret):
                found[connection.ssid] = connection
        return sorted(found.values(), key=lambda item: item.ssid)

    def _read_networkmanager(self) -> list[RouterConnection]:
        """Every wireless keyfile NetworkManager holds.

        Returns:
            The networks, with a secret where `psk-flags` says the file has
            one and without where it says the desktop's keyring does.
        """
        connections = []
        paths = [path for directory in self._nm_dirs for path in _files_in(directory)]
        for path in paths:
            parsed = _read_ini(path)
            if parsed is None:
                continue
            if parsed.get("connection", "type", fallback="") not in (
                CREDENTIAL_NM_WIFI_TYPES
            ):
                continue
            ssid = parsed.get("wifi", "ssid", fallback="") or parsed.get(
                "802-11-wireless", "ssid", fallback=""
            )
            if not ssid:
                continue
            connections.append(
                _build(
                    ssid=ssid,
                    key_mgmt_text=parsed.get("wifi-security", "key-mgmt", fallback=""),
                    secret=_networkmanager_secret(parsed),
                    is_hidden=parsed.getboolean("wifi", "hidden", fallback=False),
                    manager=CREDENTIAL_MANAGER_NM,
                )
            )
        return [item for item in connections if item is not None]

    def _read_iwd(self) -> list[RouterConnection]:
        """Every network iwd holds.

        Returns:
            The networks. iwd stores either the passphrase or the key it
            derived from it, and takes both under the same name.
        """
        connections = []
        for path in _files_in(self._iwd_dir):
            if path.suffix == CREDENTIAL_IWD_OPEN_SUFFIX:
                connections.append(
                    RouterConnection(
                        ssid=path.stem,
                        key_mgmt=ROUTER_KEY_MGMT_NONE,
                        source=_source(CREDENTIAL_MANAGER_IWD),
                    )
                )
                continue
            if path.suffix != CREDENTIAL_IWD_PSK_SUFFIX:
                continue
            parsed = _read_ini(path)
            if parsed is None:
                continue
            secret = parsed.get("Security", "PreSharedKey", fallback="") or parsed.get(
                "Security", "Passphrase", fallback=""
            )
            connections.append(
                RouterConnection(
                    ssid=path.stem,
                    key_mgmt=ROUTER_KEY_MGMT_PSK,
                    psk=secret,
                    source=_source(CREDENTIAL_MANAGER_IWD),
                )
            )
        return connections

    def _read_supplicant_files(
        self, directory: Path, manager: str
    ) -> list[RouterConnection]:
        """Every network in a directory of supplicant configurations.

        Two stores keep their networks in this format. A standalone
        `wpa_supplicant.conf` is what Raspberry Pi OS wrote for years, and
        netplan renders one per radio out of the passphrase in its own YAML —
        which is why reading netplan needs no YAML parser.

        Args:
            directory: Where to look.
            manager: Which store this is, for the entries' ``source``.

        Returns:
            The networks.
        """
        connections = []
        for path in _files_in(directory):
            if path.suffix != ".conf":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            connections += _parse_supplicant(text, manager)
        return connections


def _build(
    *, ssid: str, key_mgmt_text: str, secret: str, is_hidden: bool, manager: str
) -> RouterConnection | None:
    """One entry, or None when the network is not one the hub can join.

    Args:
        ssid: The network name.
        key_mgmt_text: How the other manager spelled the key management.
        secret: The key, empty when the file held none.
        is_hidden: Whether the network has to be probed for by name.
        manager: Which store this came out of.

    Returns:
        The network, or None for an enterprise one — importing its name with
        no way to authenticate would put a network in the list that can never
        be joined.
    """
    # A store may name several, space separated: netplan writes
    # `WPA-PSK WPA-PSK-SHA256 SAE` for one ordinary network, and reading that
    # as a single value drops it as enterprise without saying so.
    named = {word.lower() for word in key_mgmt_text.split()}
    if not named or named == {"none"}:
        key_mgmt = ROUTER_KEY_MGMT_NONE
    elif named & set(CREDENTIAL_PSK_MANAGEMENTS) - {"sae"}:
        # A network offering both is in WPA2/WPA3 transition mode. Taking it
        # as PSK associates with either; taking it as SAE fails against an
        # access point that only speaks WPA2.
        key_mgmt = ROUTER_KEY_MGMT_PSK
    elif "sae" in named:
        key_mgmt = ROUTER_KEY_MGMT_SAE
    else:
        return None
    return RouterConnection(
        ssid=ssid,
        key_mgmt=key_mgmt,
        psk=secret,
        is_hidden=is_hidden,
        source=_source(manager),
    )


def _networkmanager_secret(parsed: configparser.ConfigParser) -> str:
    """The passphrase a keyfile holds, when it holds one.

    Args:
        parsed: The keyfile.

    Returns:
        The passphrase, or an empty string when `psk-flags` says it lives in
        the desktop's keyring rather than in the file.
    """
    flags = parsed.get("wifi-security", "psk-flags", fallback=CREDENTIAL_NM_PSK_IN_FILE)
    if flags.strip() != CREDENTIAL_NM_PSK_IN_FILE:
        return ""
    return parsed.get("wifi-security", "psk", fallback="")


def _parse_supplicant(text: str, manager: str) -> list[RouterConnection]:
    """Read the `network={}` blocks of a supplicant configuration.

    Args:
        text: The file's contents.
        manager: Which store it came from.

    Returns:
        One entry per block that names a network.
    """
    connections = []
    for block in re.findall(r"network\s*=\s*\{(.*?)\}", text, re.S):
        fields = dict(re.findall(r"^\s*([A-Za-z_0-9]+)\s*=\s*(.+?)\s*$", block, re.M))
        ssid = _unquote(fields.get("ssid", ""))
        if not ssid:
            continue
        connection = _build(
            ssid=ssid,
            key_mgmt_text=fields.get("key_mgmt", ROUTER_KEY_MGMT_PSK),
            secret=_unquote(fields.get("psk", "") or fields.get("sae_password", "")),
            is_hidden=fields.get("scan_ssid", "0").strip() == "1",
            manager=manager,
        )
        if connection is not None:
            connections.append(connection)
    return connections


def _files_in(directory: Path) -> list[Path]:
    """Every readable file in a directory, or nothing when there is none.

    Args:
        directory: Where to look.

    Returns:
        The files, sorted so two runs read them in one order.
    """
    try:
        return sorted(path for path in directory.iterdir() if path.is_file())
    except OSError:
        return []


def _read_ini(path: Path) -> configparser.ConfigParser | None:
    """Parse a keyfile, or None when it cannot be read as one.

    Args:
        path: The file.

    Returns:
        The parsed file, or None. A file that is not a keyfile is not an
        error: these directories belong to somebody else and may hold
        anything.
    """
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return None
    return parser


def _source(manager: str) -> str:
    return ROUTER_SOURCE_INHERITED.format(manager=manager)


def _unquote(value: str) -> str:
    """Strip the quotes wpa_supplicant puts around a string value.

    Two forms, both of which appear in files written by tools rather than by
    people: a plain quoted string, and the `P"..."` a printf-escaped one
    carries — which is what netplan writes every SSID as.

    Args:
        value: The raw field.

    Returns:
        The text between the quotes.
    """
    stripped = value.strip()
    if stripped.startswith(SUPPLICANT_PRINTF_PREFIX):
        stripped = stripped[len(SUPPLICANT_PRINTF_PREFIX) - 1 :]
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        return stripped[1:-1]
    return stripped
