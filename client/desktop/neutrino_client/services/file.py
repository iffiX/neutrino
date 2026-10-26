"""The file service type: mounting published shares where the person asks.

A share a machine's file share serves comes with its login: at every mount
the client reads the share's ``{user, password}`` with the ``service`` frame
and asks the person nothing. A declared share, a NAS the hub does not
manage, keeps the person's own login, typed once, in a file only this
person reads. Either way the login reaches the mount through a credentials
file of that one mount, deleted once the mount answered. The place is the
system's own shape: on Linux and macOS a directory under the home,
``~/remote/<machine>-<share>`` by default; on Windows a drive letter, the
first free one by default. The privileged part of a mount is the
platform's: on Linux it goes through the root helper under ``pkexec``.

A record in the store is the hub and entry a share came from, its host, its
share, the user it last mounted as and its place, nothing more. What is
attached is this run's own. The reconcile remounts what this run attached
and lost, which is what brings a share back after the network dropped; a
record from an earlier run waits for the person to ask. A mount takes the
host and share its entry names now, and a record whose entry moved is
written back. A share the hub or the system refused for a reason the person
has to act on waits for the person: mounting it again would only be
refused again. A failed record, and one left unmounted, hold no place: each
is dropped, with a declared share's login, once its hub's list lacks its
entry, and when another record is set to mount where it was.

Every share is mounted from the hub's channel, never from its own address.
On Linux and macOS a mount takes the entry's forward of the local port
table, made before the mount and ended once the share is unmounted, and
the system mounts ``//127.0.0.1/<share>`` at that port. On Windows the
system mounts the share at the files adapter's address for the share's
machine; a share of this machine itself, an entry with ``is_own_machine``,
is mounted from ``//127.0.0.1/<share>`` at the system's own port, through no
adapter.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hashlib
import os
import re
import threading

from neutrino_client.constants import (
    CLIENT_MOUNT_RECHECK_INTERVAL_S,
    CLIENT_MOUNT_SETTLED_CODES,
)
from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    PlatformUnsupportedError,
    ShareAttachError,
)
from neutrino_client.services.base import ServiceTypeHandler, find_entry
from neutrino_client.services.files_adapter import files_machine
from neutrino_client.services.forward import FORWARD_BIND_HOST

MOUNT_RECORD_ID_LENGTH = 16
# The mount location shape of the system that mounts through the files
# adapter rather than a forward.
MOUNT_SHAPE_ADAPTER = "drive_letter"
# Where a share mounts by default under the home, and what a name keeps.
MOUNT_DEFAULT_DIR = "remote"
MOUNT_NAME_OUTSIDE = re.compile(r"[^A-Za-z0-9_-]")
# The source of a share the person declared, whose login is the person's.
MOUNT_SOURCE_DECLARED = "declared"
# The suffixes of a declared share's kept login and of one mount's
# credentials, beside each other under the credentials directory; and of the
# login a 0.5 client kept for every share, deleted at start.
MOUNT_LOGIN_SUFFIX = ".login"
MOUNT_ONCE_SUFFIX = ".mount"
MOUNT_OLD_LOGIN_SUFFIX = ".credentials"


def _no_adapter(hub_id: str, machine: str) -> str:
    """No files adapter to mount through.

    Raises:
        ShareAttachError: ``files_adapter_unavailable``, always.
    """
    raise ShareAttachError("files_adapter_unavailable", detail="no files adapter")


def mount_record_id(hub_id: str, entry_id: str, location: str) -> str:
    """The stable id one mount is kept under.

    Args:
        hub_id: The hub the entry came from.
        entry_id: The service entry mounted.
        location: The mount point.

    Returns:
        A short hex id; the same entry of the same hub at the same place is
        the same record.
    """
    digest = hashlib.sha256(f"{hub_id}\n{entry_id}\n{location}".encode("utf-8"))
    return digest.hexdigest()[:MOUNT_RECORD_ID_LENGTH]


def is_declared_share(entry: dict) -> bool:
    """Whether a share is one the person declared, with the person's own login.

    Args:
        entry: A ``file`` entry.

    Returns:
        True for a declared app's share.
    """
    return entry.get("source") == MOUNT_SOURCE_DECLARED


def place_name(text: str) -> str:
    """A machine's or a share's name as a default place spells it.

    Args:
        text: The name.

    Returns:
        The name with every character outside letters, digits, ``-`` and
        ``_`` turned into ``-``.
    """
    return MOUNT_NAME_OUTSIDE.sub("-", str(text))


def default_place(entry: dict, platform) -> str:
    """Where a share mounts when the person names no place.

    Args:
        entry: The ``file`` entry.
        platform: The machine's platform.

    Returns:
        The first free drive letter where the system mounts at one;
        ``~/remote/<machine>-<share>`` under the home otherwise.
    """
    if platform.mount_location_shape == MOUNT_SHAPE_ADAPTER:
        return platform.suggest_mount_location()
    payload = entry.get("payload") or {}
    machine = str(entry.get("device_name", "") or "") or str(payload.get("host", ""))
    share = str(payload.get("share", "") or "")
    return os.path.join(
        platform.home(),
        MOUNT_DEFAULT_DIR,
        f"{place_name(machine)}-{place_name(share)}",
    )


def _share_url(record: dict) -> str:
    return f"//{record.get('host', '')}/{record.get('share', '')}"


def _share_refusal(error: ShareAttachError) -> dict:
    params = {"detail": error.detail} if error.detail else {}
    return {"code": error.code, "params": params}


def _nobody() -> None:
    """Nobody listening for changes."""


def _no_entries() -> list:
    """No hub publishing anything."""
    return []


def _no_material(hub_id: str, entry_id: str) -> dict:
    """No hub to ask a share's login of.

    Raises:
        GatewayUnreachable: Always.
    """
    raise GatewayUnreachable("no hub to ask the share's login of")


class FileServiceHandler(ServiceTypeHandler):
    """Mounts, unmounts, reports and remounts this person's shares."""

    service_type = "file"

    def __init__(
        self,
        *,
        platform,
        store,
        credentials_dir: str,
        forwards,
        log=print,
        on_change=None,
        entries_of=None,
        open_service=None,
        adapter_host=None,
        on_adapter_idle=None,
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            credentials_dir: Where a declared share's kept login and each
                mount's credentials file live.
            forwards: The
                :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
                a share's forward lives in.
            log: Callable used for progress messages.
            on_change: Called after every change a record's row would show;
                None for nobody listening.
            entries_of: Callable ``() -> list`` giving the merged service
                list, each entry stamped with ``hub_id``, as the hubs
                publish it now; None gives no entry.
            open_service: ``open_service(hub_id, entry_id) -> dict`` reads a
                machine's share's ``{user, password}`` with the ``service``
                frame; None reads none.
            adapter_host: ``adapter_host(hub_id, machine) -> str``, the
                files adapter's address for a machine where the system
                mounts through it, the adapter brought up for it; raises
                :class:`ShareAttachError` ``files_adapter_unavailable``;
                None has no adapter.
            on_adapter_idle: Called with no arguments where the system
                mounts through the adapter, once every record is released
                for a quit; None for nobody listening.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir
        self._forwards = forwards
        self._open_service = open_service if open_service is not None else _no_material
        self._adapter_host = adapter_host if adapter_host is not None else _no_adapter
        self._on_adapter_idle = (
            on_adapter_idle if on_adapter_idle is not None else _nobody
        )
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
        self._entries_of = entries_of if entries_of is not None else _no_entries
        self._lock = threading.Lock()
        self._problems: dict = {}
        # Live step per record: queued, mounting.
        self._stages: dict = {}
        # The records this person attached in this run, by record id.
        self._attached: set = set()
        self._wakeup = threading.Event()

    def act(self, *, entries: list, body: dict):
        """Mount a share, unmount one, or save a declared share's login.

        Args:
            entries: The merged service list.
            body: ``{"action": "mount", "hub_id", "id", "path", "username",
                "password"}`` for a share, the login only for a declared
                one and the place empty for its default; ``{"action":
                "mount", "record_id"}`` to mount a record again; ``{"action":
                "unmount", "record_id"}``, the record kept; or ``{"action":
                "set", "record_id", "username", "password"}`` to save a
                declared share's new login and mount it at once.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        action = str(body.get("action", ""))
        if action == "mount" and body.get("record_id"):
            return self.remount(record_id=str(body.get("record_id", "")))
        if action == "mount":
            hub_id = str(body.get("hub_id", ""))
            entry_id = str(body.get("id", ""))
            entry = find_entry(entries, self.service_type, hub_id, entry_id)
            if entry is None:
                return {"code": "unknown_request", "params": {}}
            return self.attach(
                hub_id=hub_id,
                entry=entry,
                path=str(body.get("path", "") or ""),
                username=str(body.get("username", "") or ""),
                password=str(body.get("password", "") or ""),
            )
        if action == "unmount":
            return self.detach(record_id=str(body.get("record_id", "")))
        if action == "set":
            return self.set_login(
                record_id=str(body.get("record_id", "")),
                username=str(body.get("username", "") or ""),
                password=str(body.get("password", "") or ""),
            )
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """This person's mount records with where each stands.

        Returns:
            ``{"mounts": [rows]}``; passwords appear nowhere.
        """
        return {"mounts": self.rows()}

    def entry_fields(self, entry: dict) -> dict:
        """What the page and the command line add to one ``file`` entry.

        Args:
            entry: The entry.

        Returns:
            ``{"mount_default", "is_declared"}``: its default place, and
            whether the person's own login mounts it.
        """
        return {
            "mount_default": default_place(entry, self._platform),
            "is_declared": is_declared_share(entry),
        }

    def start(self) -> None:
        """Reconcile now and keep reconciling on a timer."""
        threading.Thread(target=self._run, daemon=True).start()

    def release(self) -> int:
        """Detach every attached record; the records and logins stay.

        Returns:
            How many records were detached.
        """
        with self._lock:
            detached = self._detach_records(sorted(self._store.mounts().items()))
        self._settle_adapter()
        return detached

    def release_hub(self, hub_id: str) -> int:
        """Detach every attached record of one hub; the records and logins stay.

        Args:
            hub_id: The hub whose shares are unmounted.

        Returns:
            How many records were detached.
        """
        with self._lock:
            detached = self._detach_records(
                [
                    (record_id, record)
                    for record_id, record in sorted(self._store.mounts().items())
                    if record.get("hub_id") == hub_id
                ]
            )
        if detached:
            self._on_change()
        return detached

    def drop_withdrawn(self, *, hub_id: str, entries: list) -> int:
        """Drop the records holding no place of one hub whose entry its list no longer has.

        Args:
            hub_id: The hub whose list arrived.
            entries: That hub's service list as it stands now; empty for a
                hub this person left.

        Returns:
            How many records were dropped.
        """
        listed = {
            str(entry.get("id", ""))
            for entry in entries
            if entry.get("type") == self.service_type
        }
        dropped = 0
        with self._lock:
            for record_id, record in sorted(self._store.mounts().items()):
                if record.get("hub_id") != hub_id:
                    continue
                if str(record.get("entry_id", "")) in listed:
                    continue
                if not self._holds_no_place(record_id, record):
                    continue
                self._drop_record(record_id)
                dropped += 1
                self._log(f"dropped the mount record {record_id}: not shared")
        if dropped:
            self._on_change()
        return dropped

    def clear_leftovers(self) -> None:
        """Detach every record an earlier run left attached, drop the
        records that name no hub, and delete every mount's credentials file
        a run left behind and every login a 0.5 client kept."""
        try:
            names = os.listdir(self._credentials_dir)
        except OSError:
            names = []
        for name in names:
            if name.endswith(MOUNT_OLD_LOGIN_SUFFIX) or name.endswith(
                MOUNT_ONCE_SUFFIX
            ):
                try:
                    os.unlink(os.path.join(self._credentials_dir, name))
                except OSError:
                    pass
        with self._lock:
            records = sorted(self._store.mounts().items())
        for record_id, record in records:
            self._discard_once(record_id)
            location = str(record.get("path", ""))
            try:
                if not self._platform.is_share_attached(location=location):
                    continue
                self._platform.detach_share(location=location)
            except (ShareAttachError, PlatformUnsupportedError) as error:
                self._log(f"could not unmount {location}: {error}")
                continue
            self._log(f"unmounted {location} after an unclean exit")
        with self._lock:
            for record_id in self._store.drop_hubless_mounts():
                self._discard_login(record_id)
                self._log(f"dropped mount record {record_id}: it names no hub")

    def attach(
        self,
        *,
        hub_id: str,
        entry: dict,
        path: str,
        username: str = "",
        password: str = "",
    ) -> dict:
        """Mount one published share at a place.

        Args:
            hub_id: The hub the entry came from.
            entry: The ``file`` entry.
            path: The place; empty takes its default.
            username: A declared share's user name; ignored for a
                machine's share, whose login the hub gives.
            password: A declared share's password, likewise.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal:
            ``mountpoint_in_use`` when another record already holds the
            place, a failed record there being dropped instead;
            ``credentials_missing`` for a declared share with no user name.
        """
        entry_id = str(entry.get("id", ""))
        payload = entry.get("payload") or {}
        is_declared = is_declared_share(entry)
        location = path or default_place(entry, self._platform)
        refusal = self._platform.validate_mount_location(location=location)
        if refusal is not None:
            return refusal
        refusal = self._tooling_refusal()
        if refusal is not None:
            return refusal
        if self._platform.mount_location_shape != MOUNT_SHAPE_ADAPTER:
            location = os.path.normpath(location)
        with self._lock:
            refusal = self._platform.prepare_mount_location(location=location)
            if refusal is not None:
                return refusal
            record_id = mount_record_id(hub_id, entry_id, location)
            kept_login = self._login_path(record_id)
            if is_declared and not username and not os.path.isfile(kept_login):
                return {"code": "credentials_missing", "params": {}}
            for old_id, old in list(self._store.mounts().items()):
                if old_id == record_id:
                    continue
                if old.get("hub_id") != hub_id or old.get("entry_id") != entry_id:
                    if str(old.get("path", "")) == location:
                        if not self._holds_no_place(old_id, old):
                            return {
                                "code": "mountpoint_in_use",
                                "params": {"path": location},
                            }
                        self._drop_record(old_id)
                        self._log(f"dropped the idle mount record at {location}")
                    continue
                old_location = str(old.get("path", ""))
                try:
                    if self._platform.is_share_attached(location=old_location):
                        self._platform.detach_share(location=old_location)
                except (ShareAttachError, PlatformUnsupportedError):
                    pass
                self._drop_record(old_id)
            record = {
                "hub_id": hub_id,
                "entry_id": entry_id,
                "host": str(payload.get("host", "")),
                "share": str(payload.get("share", "")),
                "username": username if is_declared else "",
                "path": location,
                "is_own_machine": entry.get("is_own_machine") is True,
                "is_declared": is_declared,
            }
            if is_declared and username:
                try:
                    self._platform.write_share_credentials(
                        credentials_path=kept_login,
                        username=username,
                        password=password,
                    )
                except PlatformUnsupportedError:
                    return {"code": "unsupported_platform", "params": {}}
                except OSError:
                    return {"code": "fs_refused", "params": {}}
            self._store.set_mount(record_id, record)
            self._problems.pop(record_id, None)
            self._stages[record_id] = "queued"
            self._attached.add(record_id)
            self._log(f"queued {_share_url(record)} for {location}")
        self._wakeup.set()
        self._on_change()
        return {}

    def set_login(self, *, record_id: str, username: str, password: str) -> dict:
        """Save a declared share's new login and mount it at once.

        Args:
            record_id: The record.
            username: The share's user name.
            password: The share's password.

        Returns:
            Empty on success; ``unknown_request`` for a record of no declared
            share, ``credentials_missing`` for an empty user name.
        """
        with self._lock:
            record = self._store.mounts().get(record_id)
            if record is None or record.get("is_declared") is not True:
                return {"code": "unknown_request", "params": {}}
            if not username:
                return {"code": "credentials_missing", "params": {}}
            try:
                self._platform.write_share_credentials(
                    credentials_path=self._login_path(record_id),
                    username=username,
                    password=password,
                )
            except PlatformUnsupportedError:
                return {"code": "unsupported_platform", "params": {}}
            except OSError:
                return {"code": "fs_refused", "params": {}}
            self._store.set_mount(record_id, dict(record, username=username))
        return self.remount(record_id=record_id)

    def remount(self, *, record_id: str) -> dict:
        """Mount a kept record again: a machine's share with its login read
        again, a declared share with its kept login.

        Args:
            record_id: The record to bring back.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        refusal = self._tooling_refusal()
        if refusal is not None:
            return refusal
        with self._lock:
            record = self._store.mounts().get(record_id)
            if record is None:
                return {"code": "unknown_request", "params": {}}
            self._problems.pop(record_id, None)
            self._stages[record_id] = "queued"
            self._attached.add(record_id)
            self._log(f"queued {_share_url(record)} again")
        self._wakeup.set()
        self._on_change()
        return {}

    def detach(self, *, record_id: str) -> dict:
        """Unmount one record; the record and a declared share's login are kept.

        Args:
            record_id: The record to unmount.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        with self._lock:
            record = self._store.mounts().get(record_id)
            if record is None:
                return {"code": "unknown_request", "params": {}}
            location = str(record.get("path", ""))
            try:
                if self._platform.is_share_attached(location=location):
                    self._platform.detach_share(location=location)
            except ShareAttachError as error:
                return _share_refusal(error)
            except PlatformUnsupportedError:
                return {"code": "unsupported_platform", "params": {}}
            self._problems.pop(record_id, None)
            self._stages.pop(record_id, None)
            self._attached.discard(record_id)
            self._end_forward(record)
            self._log(f"unmounted {location}; the record stays")
        return {}

    def rows(self) -> list:
        """Every record with where it stands, for the state payload.

        Returns:
            One row per record; passwords appear nowhere.
        """
        rows = []
        for record_id, record in sorted(self._store.mounts().items()):
            location = str(record.get("path", ""))
            try:
                is_attached = self._platform.is_share_attached(location=location)
            except PlatformUnsupportedError:
                is_attached = False
            problem = dict(self._problems.get(record_id, {}))
            if self._is_login_missing(record_id, record):
                problem = {"code": "credentials_missing", "params": {}}
            stage = self._stages.get(record_id, "")
            if problem.get("code"):
                state = "failed"
            elif stage:
                state = stage
            elif is_attached:
                state = "mounted"
            elif record_id in self._attached:
                state = "pending"
            else:
                state = "detached"
            rows.append(
                {
                    "record_id": record_id,
                    "hub_id": record.get("hub_id", ""),
                    "entry_id": record.get("entry_id", ""),
                    "host": record.get("host", ""),
                    "server": self._server_of(record),
                    "share": record.get("share", ""),
                    "username": record.get("username", ""),
                    "path": location,
                    "is_declared": record.get("is_declared") is True,
                    "is_attached": is_attached,
                    "state": state,
                    "code": problem.get("code", ""),
                    "params": problem.get("params", {}),
                }
            )
        return rows

    def reconcile(self) -> None:
        """Remount every record this run attached that is not attached now.

        The snapshot is taken under the lock and the mounting done outside
        it: a mount can take a while, and the control channel must go on
        answering while it does.
        """
        with self._lock:
            pending = [
                (record_id, record)
                for record_id, record in sorted(self._store.mounts().items())
                if record_id in self._attached
            ]
        for record_id, record in pending:
            self._remount(record_id, record)

    def machines(self) -> set:
        """The machines every kept record names, for the adapter's address plan.

        Returns:
            ``{(hub_id, machine)}`` as :func:`files_machine` names the machine;
            this machine itself, which takes no address, is left out.
        """
        return {
            (str(record.get("hub_id", "")), self._machine_of(record))
            for record in self._store.mounts().values()
            if not self._is_own_share(record)
        }

    def _run(self) -> None:
        while True:
            try:
                self.reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"mount reconcile crashed: {error}")
            self._wakeup.wait(timeout=CLIENT_MOUNT_RECHECK_INTERVAL_S)
            self._wakeup.clear()

    def _remount(self, record_id: str, record: dict) -> None:
        try:
            self._mount_record(record_id, record)
        finally:
            self._on_change()

    def _mount_record(self, record_id: str, record: dict) -> None:
        location = str(record.get("path", ""))
        try:
            if self._platform.is_share_attached(location=location):
                self._problems.pop(record_id, None)
                self._stages.pop(record_id, None)
                return
        except PlatformUnsupportedError:
            return
        if self._is_login_missing(record_id, record):
            self._problems[record_id] = {"code": "credentials_missing", "params": {}}
            self._stages.pop(record_id, None)
            return
        refusal = self._platform.prepare_mount_location(location=location)
        if refusal is None:
            refusal = self._tooling_refusal()
        if refusal is not None:
            self._problems[record_id] = refusal
            self._stages.pop(record_id, None)
            return
        record = self._follow_entry(record_id, record)
        self._stages[record_id] = "mounting"
        self._on_change()
        once = self._once_path(record_id)
        try:
            refusal = self._write_once(record_id, record, once)
            if refusal is not None:
                self._settle(record_id, record, refusal)
                return
            share_url, port = self._share_target(record)
            self._platform.attach_share(
                share_url=share_url,
                port=port,
                location=location,
                credentials_path=once,
            )
        except ShareAttachError as error:
            self._settle(record_id, record, _share_refusal(error))
            self._log(f"could not mount {_share_url(record)}: {error.code}")
            return
        except PlatformUnsupportedError:
            self._stages.pop(record_id, None)
            return
        except OSError as error:
            self._problems[record_id] = {
                "code": "forward_failed",
                "params": {"detail": str(error)[:200]},
            }
            self._stages.pop(record_id, None)
            return
        finally:
            self._discard_once(record_id)
        self._problems.pop(record_id, None)
        self._stages.pop(record_id, None)
        self._log(f"mounted {_share_url(record)} at {location}")

    def _write_once(self, record_id: str, record: dict, once: str) -> "dict | None":
        """Write the one mount's credentials file from the hub's or the kept login.

        Returns:
            None once written; the refusal otherwise.

        Raises:
            OSError: When the file cannot be written.
        """
        if record.get("is_declared") is True:
            username, password = _read_login(self._login_path(record_id))
        else:
            try:
                material = self._open_service(
                    str(record.get("hub_id", "")), str(record.get("entry_id", ""))
                )
            except GatewayRefusedDetail as refused:
                return {"code": refused.code, "params": dict(refused.params)}
            except GatewayUnreachable as error:
                return {"code": "hub_unreachable", "params": {"detail": str(error)}}
            username = str((material or {}).get("user", "") or "")
            password = str((material or {}).get("password", "") or "")
            if not username:
                return {"code": "credentials_missing", "params": {}}
            if record.get("username") != username:
                with self._lock:
                    held = self._store.mounts().get(record_id)
                    if held is not None:
                        self._store.set_mount(record_id, dict(held, username=username))
        try:
            self._platform.write_share_credentials(
                credentials_path=once, username=username, password=password
            )
        except PlatformUnsupportedError:
            return {"code": "unsupported_platform", "params": {}}
        username = password = ""
        return None

    def _settle(self, record_id: str, record: dict, refusal: dict) -> None:
        """Write a failed mount's refusal; one the person acts on ends its tries.

        A share refusal the person has to act on, and every refusal the hub
        gave for the share's login, is not tried again on the timer; a host
        out of reach is, since the network comes back on its own.
        """
        self._problems[record_id] = refusal
        self._stages.pop(record_id, None)
        code = refusal.get("code", "")
        is_settled = code in CLIENT_MOUNT_SETTLED_CODES or code not in (
            "share_unreachable",
            "hub_unreachable",
            "mount_failed",
        )
        if is_settled:
            self._attached.discard(record_id)
            self._end_forward(record)

    def _follow_entry(self, record_id: str, record: dict) -> dict:
        """The record with the host and share its entry names now, and
        whether its share is on this machine.

        A record whose entry moved or changed machine is written back to the
        store; one whose entry is absent, its hub being away, stands as it is.
        """
        entry = find_entry(
            self._entries_of(),
            self.service_type,
            str(record.get("hub_id", "")),
            str(record.get("entry_id", "")),
        )
        if entry is None:
            return record
        payload = entry.get("payload") or {}
        host = str(payload.get("host", "") or "")
        share = str(payload.get("share", "") or "")
        is_own = entry.get("is_own_machine") is True
        if is_own != bool(record.get("is_own_machine")):
            record = dict(record, is_own_machine=is_own)
            with self._lock:
                self._store.set_mount(record_id, record)
        if not host or (host, share) == (record.get("host"), record.get("share")):
            return record
        moved = dict(record, host=host, share=share)
        with self._lock:
            self._store.set_mount(record_id, moved)
        self._log(f"share moved to {host}: {_share_url(moved)} at {moved.get('path')}")
        return moved

    def _share_target(self, record: dict) -> "tuple[str, int]":
        """What the system mounts one record's share from, and at which port.

        Returns:
            ``(share_url, port)``: the files adapter's address for the
            share's machine and port 0 where the system mounts through the
            adapter, the loopback and port 0 there for a share of this
            machine itself, else ``//127.0.0.1/<share>`` and the port of the
            entry's forward, made here when it has none.

        Raises:
            ShareAttachError: ``files_adapter_unavailable`` when the adapter
                cannot be made.
            OSError: When the forward cannot listen.
        """
        hub_id = str(record.get("hub_id", ""))
        entry_id = str(record.get("entry_id", ""))
        share = str(record.get("share", ""))
        if self._platform.mount_location_shape == MOUNT_SHAPE_ADAPTER:
            if self._is_own_share(record):
                return f"//{FORWARD_BIND_HOST}/{share}", 0
            host = self._adapter_host(hub_id, self._machine_of(record))
            return f"//{host}/{share}", 0
        port = self._forwards.ensure(
            hub_id=hub_id, entry_id=entry_id, kind=self.service_type
        )
        return f"//{FORWARD_BIND_HOST}/{share}", port

    def _server_of(self, record: dict) -> str:
        """The server the system lists a record's share under: the loopback
        a forwarded share, and one of this machine, is mounted from, else
        the share's own host."""
        if self._platform.mount_location_shape == MOUNT_SHAPE_ADAPTER:
            if self._is_own_share(record):
                return FORWARD_BIND_HOST
            return str(record.get("host", ""))
        return FORWARD_BIND_HOST

    @staticmethod
    def _is_own_share(record: dict) -> bool:
        """Whether a record's share is on this machine, as its entry last said."""
        return record.get("is_own_machine") is True

    def _machine_of(self, record: dict) -> str:
        """The machine that provides a record's share: its device, else its host."""
        entry = find_entry(
            self._entries_of(),
            self.service_type,
            str(record.get("hub_id", "")),
            str(record.get("entry_id", "")),
        )
        if entry is None:
            return str(record.get("host", ""))
        return files_machine(entry) or str(record.get("host", ""))

    def _settle_adapter(self) -> None:
        """Let the files adapter go once no record of this run wants a share mounted; for a quit."""
        if self._platform.mount_location_shape != MOUNT_SHAPE_ADAPTER:
            return
        with self._lock:
            is_idle = not self._attached
        if is_idle:
            self._on_adapter_idle()

    def _end_forward(self, record: dict) -> None:
        """End the forward one record's share was mounted through."""
        self._forwards.stop(
            str(record.get("hub_id", "")), str(record.get("entry_id", ""))
        )

    def _detach_records(self, records: list) -> int:
        """Detach ``(record_id, record)`` pairs and forget their standing; under the lock."""
        detached = 0
        for record_id, record in records:
            location = str(record.get("path", ""))
            try:
                if self._platform.is_share_attached(location=location):
                    self._platform.detach_share(location=location)
                    detached += 1
            except (ShareAttachError, PlatformUnsupportedError) as error:
                self._log(f"could not unmount {location}: {error}")
            self._stages.pop(record_id, None)
            self._attached.discard(record_id)
            self._end_forward(record)
        return detached

    def _holds_no_place(self, record_id: str, record: dict) -> bool:
        """Whether a record holds no mount place; under the lock.

        A record holds its place while its share is mounted or being
        mounted: on its way, mounted on the system, or wanted mounted by
        this run and not failed. A failed record, and one left unmounted,
        hold none.
        """
        if record_id in self._stages:
            return False
        is_failed = record_id in self._problems or self._is_login_missing(
            record_id, record
        )
        if not is_failed and record_id in self._attached:
            return False
        try:
            return not self._platform.is_share_attached(
                location=str(record.get("path", ""))
            )
        except PlatformUnsupportedError:
            return True

    def _is_login_missing(self, record_id: str, record: dict) -> bool:
        """Whether a declared share's kept login is gone."""
        return record.get("is_declared") is True and not os.path.isfile(
            self._login_path(record_id)
        )

    def _drop_record(self, record_id: str) -> None:
        """Forget one record, its login and its standing; under the lock."""
        record = self._store.mounts().get(record_id)
        if record is not None:
            self._end_forward(record)
        self._discard_login(record_id)
        self._discard_once(record_id)
        self._store.remove_mount(record_id)
        self._problems.pop(record_id, None)
        self._stages.pop(record_id, None)
        self._attached.discard(record_id)

    def _tooling_refusal(self) -> "dict | None":
        """Refuse when the machine has no way to attach a share.

        Returns:
            None when mounting can go ahead, the typed refusal otherwise.
        """
        try:
            is_ready = self._platform.has_mount_tooling()
        except PlatformUnsupportedError:
            is_ready = True
        if is_ready:
            return None
        return {"code": "mount_tooling_missing", "params": {}}

    def _login_path(self, record_id: str) -> str:
        return os.path.join(self._credentials_dir, record_id + MOUNT_LOGIN_SUFFIX)

    def _once_path(self, record_id: str) -> str:
        return os.path.join(self._credentials_dir, record_id + MOUNT_ONCE_SUFFIX)

    def _discard_login(self, record_id: str) -> None:
        try:
            os.unlink(self._login_path(record_id))
        except OSError:
            pass

    def _discard_once(self, record_id: str) -> None:
        try:
            os.unlink(self._once_path(record_id))
        except OSError:
            pass


def _read_login(path: str) -> "tuple[str, str]":
    """A kept login's user name and password; empty when it cannot be read."""
    username = password = ""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                name, _, value = line.rstrip("\n").partition("=")
                if name == "username":
                    username = value
                elif name == "password":
                    password = value
    except OSError:
        pass
    return username, password
