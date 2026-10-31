"""SSH for other programs: ``~/.ssh/neutrino_config``, the keys and Neutrino's known_hosts.

Every program that reads an SSH configuration reaches a machine's SSH
server through the client: the client writes one block per machine that
has an ``ssh`` entry this client is allowed, across every hub, whose
``ProxyCommand`` is ``nclient ssh proxy``. A machine's host is the machine
part of its apps' local names, followed by ``.nt``; two hubs holding a
machine of one slug give each ``<machine>.<hub>.nt``. ``User`` is the
machine's first ``ssh`` entry's account. Each account's key is read with
the entry's ``service`` frame when the entries change, the entry's
``account_key_fingerprint`` among them, written to
``~/.ssh/neutrino/<host>_<account>`` at 0600, and each machine's host key
to Neutrino's own known_hosts. The client never edits ``~/.ssh/config`` by
itself; installing adds ``Include ~/.ssh/neutrino_config`` as its first
line, once, and uninstalling takes that line out and nothing else. When
the last hub is left, the configuration, the keys and the known_hosts go.

For a program that takes only a host and a port, each ``ssh`` entry is
forwarded at its fixed local port, ``127.0.0.1:<local port>``, for as long
as its hub lists it; the machine's SSH server is no app, and no Apps page
shows it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import shutil
import threading

from neutrino_client.core import files
from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    PlatformUnsupportedError,
)
from neutrino_client.services.forward import forward_refusal

# The type of the entries this file serves.
SSH_ENTRY_KIND = "ssh"
SSH_DIR_NAME = ".ssh"
SSH_CONFIG_NAME = "neutrino_config"
SSH_USER_CONFIG_NAME = "config"
SSH_KEYS_DIR_NAME = "neutrino"
SSH_KNOWN_HOSTS_NAME = "known_hosts"
SSH_HOST_SUFFIX = ".nt"
SSH_INCLUDE_LINE = "Include ~/.ssh/neutrino_config"
# The command a block's ProxyCommand runs, by system.
SSH_PROXY_PROGRAM = "nclient"
SSH_PROXY_PROGRAM_WINDOWS = "nclient.exe"
SSH_APP_ID_PREFIX = "ssh_server_"
# The local names' suffix, and what the slug rule keeps.
SSH_LOCAL_NAME_SUFFIX = ".localhost"
SSH_SLUG_OUTSIDE = re.compile(r"[^a-z0-9]+")
SSH_SLUG_LENGTH_MAX = 63


def slug(text: str, fallback: str = "machine") -> str:
    """A name as a local name spells it.

    Args:
        text: The name.
        fallback: What an empty slug reads as.

    Returns:
        The text in lowercase, each run of characters other than a to z and
        0 to 9 one ``-``, ``-`` taken off both ends, at most 63 characters.
    """
    cut = SSH_SLUG_OUTSIDE.sub("-", str(text).lower()).strip("-")[:SSH_SLUG_LENGTH_MAX]
    return cut.strip("-") or fallback


def app_machine(app: dict) -> str:
    """The machine part of one app's local name.

    Args:
        app: The app.

    Returns:
        The machine's slug, as the local name spells it; the slug of its
        device's name when it has no local name.
    """
    local_name = str(app.get("local_name", "") or "")
    labels = local_name[: -len(SSH_LOCAL_NAME_SUFFIX)].split(".")
    if local_name.endswith(SSH_LOCAL_NAME_SUFFIX) and len(labels) >= 2:
        return labels[1]
    return slug(str(app.get("device_name", "")))


def ssh_machines(entries: list, apps: list, hub_names: dict) -> list:
    """Every machine reached by ssh, as ``~/.ssh/neutrino_config`` names it.

    Args:
        entries: The published entries, each stamped with its ``hub_id``.
        apps: The apps, each stamped with its ``hub_id``.
        hub_names: ``{hub_id: hub name}``.

    Returns:
        ``[{host, hub_id, device_id, name, accounts, entries}]`` in the
        entries' order: ``host`` without ``.nt``, ``accounts`` the enabled
        accounts in the hub's order, the first the default, and
        ``entries`` the ``ssh`` entry of each.
    """
    by_app = {(app.get("hub_id"), app.get("id")): app for app in apps}
    machines: list = []
    for entry in entries:
        if entry.get("type") != SSH_ENTRY_KIND:
            continue
        key = (entry.get("hub_id"), entry.get("device_id") or entry.get("app_id"))
        found = next((row for row in machines if row["key"] == key), None)
        if found is None:
            app = by_app.get((entry.get("hub_id"), entry.get("app_id"))) or {}
            name = str(entry.get("device_name", "") or "") or str(
                (entry.get("payload") or {}).get("host", "") or ""
            )
            found = {
                "key": key,
                "machine": app_machine(app) if app else slug(name),
                "hub_id": str(entry.get("hub_id", "")),
                "device_id": str(entry.get("device_id", "")),
                "name": name,
                "accounts": [],
                "entries": [],
            }
            machines.append(found)
        account = str((entry.get("payload") or {}).get("account", "") or "")
        found["accounts"].append(account)
        found["entries"].append(entry)
    hubs_of: dict = {}
    for row in machines:
        hubs_of.setdefault(row["machine"], set()).add(row["hub_id"])
    for row in machines:
        host = row.pop("machine")
        if len(hubs_of[host]) > 1:
            host = f"{host}.{slug(hub_names.get(row['hub_id'], ''), 'hub')}"
        row["host"] = host
        row.pop("key")
    return machines


def keep_forwards(forwards, *, hub_id: str, entries: list) -> dict:
    """Forward every ``ssh`` entry of one hub at its fixed local port.

    An entry forwarded already keeps its forward; an entry the hub gave no
    number gets none.

    Args:
        forwards: The
            :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
            the forwards live in.
        hub_id: The hub whose list arrived.
        entries: That hub's service list as it stands now.

    Returns:
        ``{entry id: refusal}`` for each ``ssh`` entry with a number: empty
        while its forward listens, else the code it failed with,
        ``port_taken {port}`` among them.
    """
    outcomes = {}
    for entry in entries:
        if entry.get("type") != SSH_ENTRY_KIND:
            continue
        port = entry.get("local_port")
        if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
            continue
        entry_id = str(entry.get("id", ""))
        try:
            forwards.ensure(
                hub_id=hub_id, entry_id=entry_id, kind=SSH_ENTRY_KIND, own_port=port
            )
        except OSError as error:
            outcomes[entry_id] = forward_refusal(error)
            continue
        outcomes[entry_id] = {}
    return outcomes


def config_block(host: str, user: str, proxy_program: str) -> str:
    """One machine's block of ``~/.ssh/neutrino_config``.

    Args:
        host: The machine's host, without ``.nt``.
        user: The account ``ssh`` logs in as when it names none.
        proxy_program: ``nclient``, or ``nclient.exe`` on Windows.

    Returns:
        The block, ending with an empty line.
    """
    alias = host + SSH_HOST_SUFFIX
    return (
        f"Host {alias}\n"
        f"    User {user}\n"
        f'    ProxyCommand {proxy_program} ssh proxy "%r@%h"\n'
        f'    IdentityFile "~/.ssh/{SSH_KEYS_DIR_NAME}/{host}_%r"\n'
        "    IdentitiesOnly yes\n"
        f"    UserKnownHostsFile ~/.ssh/{SSH_KEYS_DIR_NAME}/{SSH_KNOWN_HOSTS_NAME}\n"
        f"    HostKeyAlias {alias}\n"
        "\n"
    )


def _nobody(*_args) -> None:
    """Nobody listening."""


def _no_material(hub_id: str, entry_id: str) -> dict:
    """No hub to ask a key of.

    Raises:
        GatewayUnreachable: Always.
    """
    raise GatewayUnreachable("no hub to ask the key of")


class SshConfigWriter:
    """Keeps ``~/.ssh/neutrino_config``, the keys and the known_hosts in line with the hubs."""

    def __init__(
        self,
        *,
        home: str,
        open_service=None,
        restrict_file=None,
        is_windows: bool = False,
        log=print,
        on_change=None,
        start_thread=None,
    ):
        """
        Args:
            home: This person's home directory.
            open_service: ``open_service(hub_id, entry_id) -> dict`` reads an
                ``ssh`` entry's ``{account, private_key, host_key}``; None
                reads none.
            restrict_file: ``restrict_file(path)`` leaves a key file to this
                person alone where the mode bits do not; None does nothing.
            is_windows: Whether ``ProxyCommand`` names ``nclient.exe``.
            log: Callable used for progress messages.
            on_change: Called after the configuration or the Include line
                changed; None for nobody listening.
            start_thread: ``start_thread(target)`` runs a rewrite; None uses a
                daemon thread. Tests pass one that runs inline.
        """
        self._home = home
        self._open_service = open_service if open_service is not None else _no_material
        self._restrict_file = restrict_file if restrict_file is not None else _nobody
        self._proxy_program = (
            SSH_PROXY_PROGRAM_WINDOWS if is_windows else SSH_PROXY_PROGRAM
        )
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._start_thread = start_thread if start_thread is not None else _in_thread
        self._lock = threading.Lock()
        # One rewrite or clear at a time. A rewrite deletes every file under
        # the keys directory it did not write. A rewrite keeps it locked
        # across a hub's replies, so ``refresh`` never takes it.
        self._rewrite_lock = threading.Lock()
        # What the last rewrite was made from; a rewrite runs when it changes.
        self._written: "tuple | None" = None
        # The newest refresh's machines, until a rewrite takes them.
        self._newest: "list | None" = None
        self._is_stopped = False

    @property
    def config_path(self) -> str:
        """``~/.ssh/neutrino_config``."""
        return os.path.join(self._home, SSH_DIR_NAME, SSH_CONFIG_NAME)

    @property
    def keys_dir(self) -> str:
        """``~/.ssh/neutrino``."""
        return os.path.join(self._home, SSH_DIR_NAME, SSH_KEYS_DIR_NAME)

    @property
    def user_config_path(self) -> str:
        """``~/.ssh/config``."""
        return os.path.join(self._home, SSH_DIR_NAME, SSH_USER_CONFIG_NAME)

    def refresh(self, *, entries: list, apps: list, hub_names: dict) -> None:
        """Rewrite the configuration when the machines reached by ssh changed,
        or a host key or an account's key did.

        Args:
            entries: The published entries of every connected hub, stamped
                with their ``hub_id``.
            apps: The apps of every connected hub, stamped likewise.
            hub_names: ``{hub_id: hub name}``.
        """
        machines = ssh_machines(entries, apps, hub_names)
        shape = tuple(
            (
                row["host"],
                tuple(
                    (
                        entry.get("hub_id"),
                        entry.get("id"),
                        str(
                            (entry.get("payload") or {}).get("host_key_fingerprint", "")
                        ),
                        str(
                            (entry.get("payload") or {}).get(
                                "account_key_fingerprint", ""
                            )
                        ),
                    )
                    for entry in row["entries"]
                ),
            )
            for row in machines
        )
        with self._lock:
            if self._is_stopped or shape == self._written:
                return
            self._written = shape
            self._newest = machines
        self._start_thread(self._rewrite_newest)

    def stop(self) -> None:
        """End the rewrites. A rewrite running finishes first. Idempotent."""
        with self._rewrite_lock:
            with self._lock:
                self._is_stopped = True
                self._newest = None

    def clear(self) -> None:
        """Delete the configuration, the keys and the known_hosts: no hub is left."""
        with self._rewrite_lock:
            with self._lock:
                self._written = None
                self._newest = None
            for path in (self.config_path,):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            shutil.rmtree(self.keys_dir, ignore_errors=True)
        self._log("removed the SSH configuration: no hub is joined")
        self._on_change()

    def config_text(self) -> dict:
        """The configuration as it stands on disk.

        Returns:
            ``{"path", "text"}``, the text empty while there is none.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as stream:
                text = stream.read()
        except OSError:
            text = ""
        return {"path": self.config_path, "text": text}

    def is_include_installed(self) -> bool:
        """Whether ``~/.ssh/config`` holds the Include line."""
        return any(
            line.strip() == SSH_INCLUDE_LINE for line in self._user_config_lines()
        )

    def set_include(self, is_installed: bool) -> None:
        """Add the Include line as ``~/.ssh/config``'s first line, once, or take it out.

        Args:
            is_installed: Whether the line goes in.

        Raises:
            OSError: When ``~/.ssh/config`` cannot be written.
        """
        lines = self._user_config_lines()
        kept = [line for line in lines if line.strip() != SSH_INCLUDE_LINE]
        if is_installed:
            if lines and lines[0].strip() == SSH_INCLUDE_LINE:
                return
            kept = [SSH_INCLUDE_LINE + "\n"] + kept
        elif kept == lines:
            return
        self._ensure_ssh_dir()
        _write_private(self.user_config_path, "".join(kept))
        self._log(
            "added the Include line to ~/.ssh/config"
            if is_installed
            else "took the Include line out of ~/.ssh/config"
        )
        self._on_change()

    def _rewrite_newest(self) -> None:
        """Rewrite for the newest refresh's machines, unless a rewrite took them."""
        with self._rewrite_lock:
            with self._lock:
                machines, self._newest = self._newest, None
            if machines is not None:
                self._rewrite(machines)

    def _rewrite(self, machines: list) -> None:
        """Write the keys, the known_hosts and the configuration for these machines."""
        self._ensure_ssh_dir()
        os.makedirs(self.keys_dir, mode=0o700, exist_ok=True)
        blocks = []
        known_hosts = []
        kept_keys = set()
        for row in machines:
            host = row["host"]
            user = row["accounts"][0] if row["accounts"] else ""
            blocks.append(config_block(host, user, self._proxy_program))
            for entry in row["entries"]:
                account = str((entry.get("payload") or {}).get("account", "") or "")
                key_name = f"{host}_{account}"
                material = self._material(entry)
                if material is None:
                    if os.path.isfile(os.path.join(self.keys_dir, key_name)):
                        kept_keys.add(key_name)
                    continue
                private_key = str(material.get("private_key", "") or "")
                host_key = str(material.get("host_key", "") or "").strip()
                if private_key:
                    self._write_key(key_name, private_key)
                    kept_keys.add(key_name)
                if host_key:
                    line = f"{host}{SSH_HOST_SUFFIX} {host_key}\n"
                    if line not in known_hosts:
                        known_hosts.append(line)
                private_key = ""
        self._drop_keys(kept_keys)
        if known_hosts:
            _write_private(
                os.path.join(self.keys_dir, SSH_KNOWN_HOSTS_NAME), "".join(known_hosts)
            )
        _write_private(self.config_path, "".join(blocks))
        self._log(f"wrote the SSH configuration for {len(machines)} machines")
        self._on_change()

    def _material(self, entry: dict) -> "dict | None":
        """One entry's key and host key from the hub; None when it does not give them."""
        try:
            return self._open_service(
                str(entry.get("hub_id", "")), str(entry.get("id", ""))
            )
        except (GatewayRefusedDetail, GatewayUnreachable) as error:
            self._log(f"no SSH key for {entry.get('id', '')}: {error}")
            return None

    def _write_key(self, name: str, private_key: str) -> None:
        """Write one account's key at 0600, left to this person alone."""
        path = os.path.join(self.keys_dir, name)
        text = private_key if private_key.endswith("\n") else private_key + "\n"
        _write_private(path, text)
        try:
            self._restrict_file(path)
        except (OSError, PlatformUnsupportedError) as error:
            self._log(f"could not restrict {path}: {error}")

    def _drop_keys(self, kept: set) -> None:
        """Delete every key file of an entry that left the list."""
        try:
            names = os.listdir(self.keys_dir)
        except OSError:
            return
        for name in names:
            if name == SSH_KNOWN_HOSTS_NAME or name in kept:
                continue
            try:
                os.unlink(os.path.join(self.keys_dir, name))
            except OSError:
                pass

    def _ensure_ssh_dir(self) -> None:
        """Make ``~/.ssh`` at 0700 when it is missing."""
        directory = os.path.join(self._home, SSH_DIR_NAME)
        if not os.path.isdir(directory):
            os.makedirs(directory, mode=0o700, exist_ok=True)

    def _user_config_lines(self) -> list:
        """``~/.ssh/config``'s lines, each with its ending; empty when absent."""
        try:
            with open(self.user_config_path, "r", encoding="utf-8") as stream:
                return stream.readlines()
        except OSError:
            return []


def _write_private(path: str, text: str) -> None:
    """Write a file whole at 0600, through a temporary file of its own beside it."""
    files.write_text(path, text, mode=0o600)


def _in_thread(target) -> None:
    """Run a rewrite on a daemon thread of its own."""
    threading.Thread(target=target, name="client_ssh_config", daemon=True).start()
