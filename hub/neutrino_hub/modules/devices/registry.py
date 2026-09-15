"""The device list the panel shows.

A device is a row in ``devices.json`` keyed by the binding id the hub
generates. The row holds what is true of the machine, its ``machine_id`` and
every MAC its agent has reported on its link, beside what a person typed. A
scan row is matched to a device by any stored MAC; one no device claims is
shown under a temporary ``scan:<mac>`` id and given an id of its own the
first time a person acts on it.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from uuid import uuid4

from neutrino_hub.modules.devices.constants import (
    DEVICE_MAC_PATTERN,
    DEVICE_SCAN_ID_PREFIX,
)
from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.lan_scan import DiscoveredDevice
from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

DEVICES_CONFIG_PATH = "devices/devices.json"
AGENT_TOKEN_BYTES = 24


def scan_id(mac_address: str) -> str:
    """The temporary id a scan row no device claims is shown under.

    Args:
        mac_address: The scanned MAC.

    Returns:
        ``scan:<mac>``, the MAC lowercased.
    """
    return f"{DEVICE_SCAN_ID_PREFIX}{mac_address.lower()}"


def normalized_mac(value: str) -> str:
    """One MAC as the registry stores it.

    Args:
        value: What was reported or scanned.

    Returns:
        Lowercase, colon separated; empty when ``value`` is not a MAC.
    """
    text = str(value or "").strip()
    if not re.fullmatch(DEVICE_MAC_PATTERN, text):
        return ""
    return text.lower().replace("-", ":")


def _token_digest(token: str) -> str:
    """The stored form of a heartbeat token.

    Args:
        token: The raw token an agent holds.

    Returns:
        Its SHA-256 hex.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _scanned_mac(device_id: str) -> str:
    """The MAC a ``scan:`` id names, empty for any other id."""
    if not device_id.startswith(DEVICE_SCAN_ID_PREFIX):
        return ""
    return normalized_mac(device_id[len(DEVICE_SCAN_ID_PREFIX) :])


def _list_order(device: "ManagedDevice") -> tuple:
    """Stored devices first, then the ones a scan saw, then by name."""
    return (
        not device.is_stored,
        not device.is_online,
        (device.name or device.link_mac or device.id).lower(),
    )


@dataclass
class DeviceClientInfo:
    """State reported by the neutrino_agent agent on a device.

    Attributes:
        token_sha256: SHA-256 hex of the shared secret the agent
            authenticates its channel with; the raw token exists only in
            the enroll reply and on the device.
    """

    token_sha256: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceClientInfo":
        """Build from the stored ``client`` block.

        Args:
            data: The stored block.

        Returns:
            The parsed info.
        """
        return cls(token_sha256=data.get("token_sha256"))

    def to_dict(self) -> dict:
        """Serialize the persistent fields.

        What an agent reports, its version, when it was last seen, its
        metrics, is runtime state and stays in memory.

        Returns:
            A JSON-ready object.
        """
        return {"token_sha256": self.token_sha256}


@dataclass
class ManagedDevice:
    """One device, as stored plus whatever the latest scan learned.

    Attributes:
        id: The binding id, or ``scan:<mac>`` for a scan row no device
            claims.
        name: User-chosen label.
        machine_id: The machine's own id, as its agent reported it.
        mac_addresses: Every MAC the agent has reported on its link, sorted.
        link_mac: The MAC the agent's socket most recently ran on.
        ipv4_address: Address from the latest scan, or where the agent's
            channel comes from.
        icon: User-chosen icon key.
        vendor: OUI vendor string from the scan.
        is_online: Whether the latest scan saw it.
        ssh: Stored SSH settings, when configured.
        client: Agent state.
        shown_modules: The module tabs its Modules page shows; empty means
            the modules its reports name.
    """

    id: str
    name: str | None = None
    machine_id: str = ""
    mac_addresses: list = field(default_factory=list)
    link_mac: str = ""
    ipv4_address: str = ""
    icon: str | None = None
    vendor: str = ""
    is_online: bool = False
    ssh: dict | None = None
    client: DeviceClientInfo = field(default_factory=DeviceClientInfo)
    shown_modules: list = field(default_factory=list)

    @property
    def is_scan_row(self) -> bool:
        """Whether this is a scan row no stored device claims."""
        return self.id.startswith(DEVICE_SCAN_ID_PREFIX)

    @property
    def is_stored(self) -> bool:
        """Whether this device is a row in ``devices.json``."""
        return not self.is_scan_row

    @property
    def has_ssh(self) -> bool:
        """Whether SSH credentials are stored for this device."""
        return bool(self.ssh and self.ssh.get("host") and self.ssh.get("username"))

    @property
    def is_managed(self) -> bool:
        """Whether an agent token was issued for this device and still stands.

        Whether the agent is there right now is the session registry's
        answer, not this one's.
        """
        return bool(self.client.token_sha256)

    def to_dict(self) -> dict:
        """Serialize to the ``devices.json`` row shape.

        Returns:
            A JSON-ready object.
        """
        return {
            "name": self.name,
            "icon": self.icon,
            "machine_id": self.machine_id,
            "mac_addresses": sorted(self.mac_addresses),
            "link_mac": self.link_mac,
            "ssh": self.ssh,
            "client": self.client.to_dict(),
            "shown_modules": list(self.shown_modules),
        }


class DeviceRegistry:
    """Reads, merges, and writes the device list.

    Every write re-reads the file under the config lock first, so a writer
    holding an older snapshot puts back nothing another writer changed.
    """

    def __init__(self):
        self._stored = self._read_stored()

    def merged(self, discovered: list[DiscoveredDevice]) -> list[ManagedDevice]:
        """Combine the stored devices with a scan result.

        Args:
            discovered: What the latest scan found; may be empty, in which case
                only stored devices are returned and all are marked offline.

        Returns:
            Every known device, stored ones first, then scan-only ones under
            their ``scan:`` ids.
        """
        devices = {
            device_id: self._from_stored(device_id, entry)
            for device_id, entry in self._stored.items()
        }
        by_mac = {
            mac: device for device in devices.values() for mac in device.mac_addresses
        }
        for found in discovered:
            device = by_mac.get(found.mac_address)
            if device is None:
                device = ManagedDevice(
                    id=scan_id(found.mac_address),
                    mac_addresses=[found.mac_address],
                    link_mac=found.mac_address,
                )
                devices[device.id] = device
                by_mac[found.mac_address] = device
            device.ipv4_address = found.ipv4_address or device.ipv4_address
            device.vendor = found.vendor or device.vendor
            device.is_online = device.is_online or found.is_online
        return sorted(devices.values(), key=_list_order)

    def get(self, device_id: str) -> "ManagedDevice | None":
        """Read one device.

        Args:
            device_id: A stored id, or a ``scan:<mac>`` id.

        Returns:
            The stored device; a blank scan row for a ``scan:`` id naming a
            MAC; None for anything else.
        """
        entry = self._stored.get(device_id)
        if entry is not None:
            return self._from_stored(device_id, entry)
        mac = _scanned_mac(device_id)
        if mac:
            return ManagedDevice(id=scan_id(mac), mac_addresses=[mac], link_mac=mac)
        return None

    def all_stored(self) -> list[ManagedDevice]:
        """Read every stored device, without scanning.

        Returns:
            One device per stored row.
        """
        return [
            self._from_stored(device_id, entry)
            for device_id, entry in self._stored.items()
        ]

    def create(
        self, name: "str | None", *, machine_id: str = "", link_mac: str = ""
    ) -> ManagedDevice:
        """Store a new device under an id of its own.

        Args:
            name: What the device is called; blank keeps it unnamed.
            machine_id: The machine's own id, when its agent reported one.
            link_mac: The MAC its agent's socket runs on, when reported.

        Returns:
            The stored device.
        """
        mac = normalized_mac(link_mac)
        device = ManagedDevice(
            id=uuid4().hex,
            name=name or None,
            machine_id=machine_id,
            mac_addresses=[mac] if mac else [],
            link_mac=mac,
        )
        self._store(device)
        return device

    def adopt(self, device_id: str) -> ManagedDevice:
        """The stored row for an id, made for a scan row on its first use.

        Args:
            device_id: A stored id, or a ``scan:<mac>`` id.

        Returns:
            The stored device; a scan row comes back under a fresh id with
            its MAC recorded.

        Raises:
            KeyError: If ``device_id`` names neither.
        """
        with CONFIG_WRITE_LOCK:
            device = self._fresh(device_id)
            if device is None:
                raise KeyError(f"no device {device_id!r}")
            if device.is_scan_row:
                device = ManagedDevice(
                    id=uuid4().hex,
                    mac_addresses=list(device.mac_addresses),
                    link_mac=device.link_mac,
                )
                self._store(device)
            return device

    def annotate(self, device_id: str, annotation: dict) -> ManagedDevice:
        """Apply a partial update to one device and persist it.

        Args:
            device_id: A stored id, or a ``scan:<mac>`` id, which is adopted.
            annotation: Any of ``name``, ``icon``, ``ssh``, ``shown_modules``.

        Returns:
            The stored device after the update.

        Raises:
            KeyError: If ``device_id`` names no device.
        """
        with CONFIG_WRITE_LOCK:
            device = self.adopt(device_id)
            if "name" in annotation:
                device.name = annotation["name"]
            if "icon" in annotation:
                device.icon = annotation["icon"]
            if "ssh" in annotation:
                device.ssh = annotation["ssh"]
            if "shown_modules" in annotation:
                device.shown_modules = [
                    str(name) for name in annotation["shown_modules"]
                ]
            self._store(device)
            return device

    def forget(self, device_id: str) -> None:
        """Drop a device's row, and the host key pinned to it.

        The key is dropped only where no other row still names the same
        host and port.

        Args:
            device_id: The device. Unknown ids are ignored.
        """
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            entry = self._stored.get(device_id, {})
            ssh = entry.get("ssh") or {}
            if ssh.get("host") and not self._others_on(device_id, ssh):
                DeviceHostKeyStore().forget(ssh["host"], ssh.get("port", 22))
            self._stored.pop(device_id, None)
            self._write_stored()

    def issue_token(self, device_id: str) -> str:
        """Create a heartbeat token for a device, storing only its hash.

        A fresh token is generated every time, so reinstalling invalidates
        the old one. The device does not become managed here: the first
        heartbeat is what proves an agent is there.

        Args:
            device_id: The stored device.

        Returns:
            The new raw token, for the enroll reply alone.

        Raises:
            KeyError: If ``device_id`` names no stored device.
        """
        with CONFIG_WRITE_LOCK:
            device = self._require(device_id)
            token = secrets.token_urlsafe(AGENT_TOKEN_BYTES)
            device.client.token_sha256 = _token_digest(token)
            self._store(device)
            return token

    def find_by_token(self, token: str) -> "ManagedDevice | None":
        """Look up the device a heartbeat token belongs to.

        Args:
            token: The token presented by an agent.

        Returns:
            The matching device, or None when the token is unknown.
        """
        presented = _token_digest(token)
        for device_id, entry in self._stored.items():
            stored = entry.get("client", {}).get("token_sha256")
            if stored and secrets.compare_digest(stored, presented):
                return self._from_stored(device_id, entry)
        return None

    def find_by_machine_id(self, machine_id: str) -> "ManagedDevice | None":
        """Look up the device a machine id belongs to.

        Args:
            machine_id: The id a machine reports for itself.

        Returns:
            The matching device, or None when no row records it or the id
            is blank.
        """
        if not machine_id:
            return None
        for device_id, entry in self._stored.items():
            if entry.get("machine_id") == machine_id:
                return self._from_stored(device_id, entry)
        return None

    def drop_token(self, device_id: str) -> None:
        """Record that a device's agent has left.

        The token goes so the old one cannot beat again; the name, the icon
        and the SSH credentials stay.

        Args:
            device_id: The device. Unknown ids are ignored.
        """
        with CONFIG_WRITE_LOCK:
            device = self._fresh(device_id)
            if device is None or device.is_scan_row:
                return
            device.client.token_sha256 = None
            self._store(device)

    def note_machine(
        self, device_id: str, *, machine_id: str = "", link_mac: str = ""
    ) -> bool:
        """Record what a machine reports of itself, writing only on a change.

        Args:
            device_id: The stored device.
            machine_id: The machine's own id; blank leaves the stored one.
            link_mac: The MAC the agent's socket runs on; blank or not a
                MAC leaves the stored set and the link MAC alone.

        Returns:
            True when the row was written: the id was new, the MAC set grew,
            or the link MAC moved.
        """
        mac = normalized_mac(link_mac)
        with CONFIG_WRITE_LOCK:
            device = self._fresh(device_id)
            if device is None or device.is_scan_row:
                return False
            is_changed = False
            if machine_id and machine_id != device.machine_id:
                device.machine_id = machine_id
                is_changed = True
            if mac and mac not in device.mac_addresses:
                device.mac_addresses = sorted(device.mac_addresses + [mac])
                is_changed = True
            if mac and mac != device.link_mac:
                device.link_mac = mac
                is_changed = True
            if is_changed:
                self._store(device)
            return is_changed

    def _others_on(self, device_id: str, ssh: dict) -> bool:
        """Whether another stored device is reached at this host and port."""
        for other_id, entry in self._stored.items():
            if other_id == device_id:
                continue
            other = entry.get("ssh") or {}
            if other.get("host") == ssh.get("host") and other.get(
                "port", 22
            ) == ssh.get("port", 22):
                return True
        return False

    def _from_stored(self, device_id: str, entry: dict) -> ManagedDevice:
        return ManagedDevice(
            id=device_id,
            name=entry.get("name"),
            machine_id=str(entry.get("machine_id", "") or ""),
            mac_addresses=sorted(
                mac
                for mac in (
                    normalized_mac(value) for value in entry.get("mac_addresses") or []
                )
                if mac
            ),
            link_mac=normalized_mac(entry.get("link_mac", "")),
            icon=entry.get("icon"),
            ssh=entry.get("ssh"),
            client=DeviceClientInfo.from_dict(entry.get("client", {})),
            shown_modules=[str(name) for name in entry.get("shown_modules") or []],
        )

    def _fresh(self, device_id: str) -> "ManagedDevice | None":
        """One device read again under the write lock."""
        self._stored = self._read_stored()
        return self.get(device_id)

    def _require(self, device_id: str) -> ManagedDevice:
        """One stored device read again under the write lock."""
        device = self._fresh(device_id)
        if device is None or device.is_scan_row:
            raise KeyError(f"no stored device {device_id!r}")
        return device

    def _store(self, device: ManagedDevice) -> None:
        with CONFIG_WRITE_LOCK:
            self._stored = self._read_stored()
            self._stored[device.id] = device.to_dict()
            self._write_stored()

    def _read_stored(self) -> dict:
        try:
            data = read_config(DEVICES_CONFIG_PATH)
        except FileNotFoundError:
            return {}
        return {
            str(device_id): entry
            for device_id, entry in data.get("devices", {}).items()
        }

    def _write_stored(self) -> None:
        write_config(DEVICES_CONFIG_PATH, {"devices": self._stored})
