"""Remembering which host key belongs to which device.

The panel holds sudo passwords for every machine it manages and types them
into SSH sessions. Connecting without checking the host key means anything
that can answer on the LAN — a machine that took the address by DHCP, or
somebody sitting between — is handed those passwords by the gateway itself.

What is done instead is what a person does at an ssh prompt, minus the prompt:
the key offered the first time is recorded, and every connection after that has
to present the same one. The first connection is still taken on trust, so this
does not defend against somebody who is already in place when a device is
added; it does mean a key that changes afterwards stops the gateway rather than
being accepted in silence.

The file is in the format `ssh` itself uses, so a person can read it, and it
lives beside the device records because that is what it is: one more thing
known about a machine.

Not pure: reads and writes a file.
"""

from pathlib import Path

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR

# Where the keys live, and the mode they are written with. Not a secret — a
# public key is public — but it decides who the gateway will talk to, so it is
# not something another account should be able to edit.
DEVICE_KNOWN_HOSTS_PATH = UTILS_CONFIG_DIR / "devices" / "known_hosts"
DEVICE_KNOWN_HOSTS_MODE = 0o600

# The port that needs no bracket, the way OpenSSH writes it.
DEVICE_DEFAULT_SSH_PORT = 22


class DeviceHostKeyStore:
    """The host keys this gateway has seen, in OpenSSH's own format."""

    def __init__(self, *, path: Path = DEVICE_KNOWN_HOSTS_PATH):
        """
        Args:
            path: The known_hosts file to read and write.
        """
        self._path = path

    def known_hosts_for(self, host: str, port: int) -> "bytes | None":
        """The recorded keys for one device, for asyncssh to check against.

        Args:
            host: Address or hostname.
            port: SSH port.

        Returns:
            known_hosts content naming this device, or None when it has never
            been seen — which is what makes the first connection possible.
        """
        entries = [
            line
            for line in self._lines()
            if line.split(" ", 1)[0] == host_pattern(host, port)
        ]
        if not entries:
            return None
        return ("\n".join(entries) + "\n").encode()

    def has(self, host: str, port: int) -> bool:
        """Whether this device's key has been recorded.

        Args:
            host: Address or hostname.
            port: SSH port.

        Returns:
            True when a key is on file.
        """
        return self.known_hosts_for(host, port) is not None

    def learn(self, host: str, port: int, public_key: str) -> None:
        """Record the key a device presented, if it has none on file.

        Only ever adds. A device whose key has changed is a question for a
        person, so replacing one silently is exactly what must not happen
        here; see :meth:`forget`.

        Args:
            host: Address or hostname.
            port: SSH port.
            public_key: The key in OpenSSH's one-line form, as
                ``ssh-ed25519 AAAA...``.
        """
        if self.has(host, port) or not public_key.strip():
            return
        entry = f"{host_pattern(host, port)} {public_key.strip()}"
        self._write(self._lines() + [entry])

    def forget(self, host: str, port: int) -> None:
        """Drop what is known about a device, so the next connection relearns.

        This is what a rebuilt machine needs: its key is legitimately new, and
        somebody has decided so.

        Args:
            host: Address or hostname.
            port: SSH port.
        """
        pattern = host_pattern(host, port)
        kept = [line for line in self._lines() if line.split(" ", 1)[0] != pattern]
        self._write(kept)

    def _lines(self) -> list:
        """Every entry on file, comments and blanks dropped."""
        if not self._path.exists():
            return []
        return [
            line.strip()
            for line in self._path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def _write(self, entries: list) -> None:
        """Replace the file with these entries."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("\n".join(entries) + "\n" if entries else "")
        self._path.chmod(DEVICE_KNOWN_HOSTS_MODE)


def host_pattern(host: str, port: int) -> str:
    """How OpenSSH names a host and port in a known_hosts line.

    Args:
        host: Address or hostname.
        port: SSH port.

    Returns:
        The bare host on port 22, and ``[host]:port`` otherwise.
    """
    if port == DEVICE_DEFAULT_SSH_PORT:
        return host
    return f"[{host}]:{port}"
