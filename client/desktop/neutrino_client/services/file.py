"""The file service type: mounting published shares where the person asks.

Config asks for the share's own username, password and a path; the password
becomes a credentials file only this person reads and never travels to the
hub. Mount attaches, Unmount detaches. The privileged part of a mount is the
platform's: on Linux it goes through the root helper under ``pkexec``.

A record in the store is the hub and entry a share came from, the login and
the path this person typed, nothing more. Where the system places a volume
itself, on macOS, the path is empty until the attach answers with the mount
point, and empty again once it is detached. What is attached is this run's
own. The reconcile remounts what this run attached and lost, which is what
brings a share back after the network dropped; a record from an earlier run
waits for the person to ask. A mount takes the host and share its entry
names now, and a record whose entry moved is written back; an entry that is
absent, its hub being away, leaves the record as it is. A record whose
credentials file is gone reports
``credentials_missing`` and waits for the password to be entered again, and
one the share refused for its login, its access or its name waits the same
way: mounting it again would only be refused again. A failed record, and one
left unmounted, hold no place: each is dropped once its hub's list lacks its
entry, as after the hub is left, and when another
record is set to mount where it was. A record that names no
hub was written by an older build and is dropped at start, after whatever it
left mounted is unmounted by path.

Every share is mounted from the hub's channel, never from its own address.
On Linux and macOS a mount takes the entry's forward of the local port
table, made before the mount and ended once the share is unmounted, and
the system mounts ``//127.0.0.1/<share>`` at that port. On Windows the
system mounts the share at the files adapter's address for the share's
machine, which the resident's adapter names and brings up for it; once no
record of this run wants a share mounted any more, the adapter is let go. A
share of this machine itself, an entry with ``is_own_machine``, is mounted
on Windows from ``//127.0.0.1/<share>`` at the system's own port, through
no adapter, since Windows refuses a login that comes back to the machine.
A mount an earlier run left
standing, at a device's address by an older build among them, is unmounted
at start like every leftover, and the person's next Mount goes through the
hub.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hashlib
import os
import threading

from neutrino_client.constants import (
    CLIENT_MOUNT_RECHECK_INTERVAL_S,
    CLIENT_MOUNT_SETTLED_CODES,
)
from neutrino_client.exceptions import PlatformUnsupportedError, ShareAttachError
from neutrino_client.services.base import ServiceTypeHandler, find_entry
from neutrino_client.services.files_adapter import files_machine
from neutrino_client.services.forward import FORWARD_BIND_HOST

MOUNT_RECORD_ID_LENGTH = 16
# The mount location shape of the system that mounts through the files
# adapter rather than a forward.
MOUNT_SHAPE_ADAPTER = "drive_letter"
MOUNT_SHAPE_VOLUME = "volume"


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
        A short hex id; the same entry of the same hub at the same path is
        the same record.
    """
    digest = hashlib.sha256(f"{hub_id}\n{entry_id}\n{location}".encode("utf-8"))
    return digest.hexdigest()[:MOUNT_RECORD_ID_LENGTH]


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
        adapter_host=None,
        on_adapter_idle=None,
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            credentials_dir: Where the per-record credentials files live.
            forwards: The
                :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
                a share's forward lives in.
            log: Callable used for progress messages.
            on_change: Called after every change a record's row would show;
                None for nobody listening.
            entries_of: Callable ``() -> list`` giving the merged service
                list, each entry stamped with ``hub_id``, as the hubs
                publish it now; None gives no entry.
            adapter_host: ``adapter_host(hub_id, machine) -> str``, the
                files adapter's address for a machine where the system
                mounts through it, the adapter brought up for it; raises
                :class:`ShareAttachError` ``files_adapter_unavailable``;
                None has no adapter.
            on_adapter_idle: Called with no arguments where the system
                mounts through the adapter, once every record is released
                for a quit; an unmount, a failed mount or a hub's release
                leaves the adapter up, since the system's SMB client keeps a
                connection to an address for a while and one taken away and
                brought back under it fails the next mounts there. None for
                nobody listening.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir
        self._forwards = forwards
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
        """Mount a share with the staged config, or unmount one record.

        Args:
            entries: The merged service list.
            body: ``{"action": "mount", "hub_id", "id", "username",
                "password", "path"}`` for a fresh or reconfigured mount,
                ``{"action": "mount", "record_id"}`` to remount with the
                kept credentials, or ``{"action": "unmount", "record_id"}``;
                the record and its credentials stay.

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
                entry_id=entry_id,
                payload=entry.get("payload") or {},
                username=str(body.get("username", "")),
                password=str(body.get("password", "")),
                path=str(body.get("path", "")),
            )
        if action == "unmount":
            return self.detach(record_id=str(body.get("record_id", "")))
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """This person's mount records with where each stands.

        Returns:
            ``{"mounts": [rows]}``; passwords appear nowhere.
        """
        return {"mounts": self.rows()}

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
        """Detach every record an earlier run left attached, then drop the
        records that name no hub and their credentials."""
        with self._lock:
            records = sorted(self._store.mounts().items())
        for record_id, record in records:
            location = str(record.get("path", ""))
            try:
                if not self._platform.is_share_attached(location=location):
                    continue
                self._platform.detach_share(location=location)
            except (ShareAttachError, PlatformUnsupportedError) as error:
                self._log(f"could not unmount {location}: {error}")
                continue
            with self._lock:
                self._forget_volume(record_id)
            self._log(f"unmounted {location} after an unclean exit")
        with self._lock:
            for record_id in self._store.drop_hubless_mounts():
                self._discard_credentials(record_id)
                self._log(f"dropped mount record {record_id}: it names no hub")

    def attach(
        self,
        *,
        hub_id: str,
        entry_id: str,
        payload: dict,
        username: str,
        password: str,
        path: str,
    ) -> dict:
        """Mount one published share at a path.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry's id in that hub's list.
            payload: The entry's payload, naming the host and share.
            username: The share's own username.
            password: The share's own password; it stays on this machine.
            path: The mount point; ignored where the system places a volume.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal;
            ``mountpoint_in_use`` when another record already holds the
            path; a failed record there is dropped instead.
        """
        refusal = self._platform.validate_mount_location(location=path)
        if refusal is not None:
            return refusal
        refusal = self._tooling_refusal()
        if refusal is not None:
            return refusal
        location = "" if self._is_volume() else os.path.normpath(path)
        with self._lock:
            refusal = self._platform.prepare_mount_location(location=location)
            if refusal is not None:
                return refusal
            for old_id, old in list(self._store.mounts().items()):
                if old.get("hub_id") != hub_id or old.get("entry_id") != entry_id:
                    if location and str(old.get("path", "")) == location:
                        if not self._holds_no_place(old_id, old):
                            return {
                                "code": "mountpoint_in_use",
                                "params": {"path": path},
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
            record_id = mount_record_id(hub_id, entry_id, location)
            record = {
                "hub_id": hub_id,
                "entry_id": entry_id,
                "host": str(payload.get("host", "")),
                "share": str(payload.get("share", "")),
                "username": username,
                "path": location,
            }
            try:
                self._platform.write_share_credentials(
                    credentials_path=self._credentials_path(record_id),
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
            self._log(f"queued {_share_url(record)} for {location or 'a volume'}")
        self._wakeup.set()
        self._on_change()
        return {}

    def remount(self, *, record_id: str) -> dict:
        """Mount a kept record again with the credentials it saved.

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
        """Unmount one record; the record and its credentials are kept.

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
            self._forget_volume(record_id)
            self._problems.pop(record_id, None)
            self._stages.pop(record_id, None)
            self._attached.discard(record_id)
            self._end_forward(record)
            self._log(f"unmounted {location}; the record and login stay")
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
            if not os.path.isfile(self._credentials_path(record_id)):
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
        if not os.path.isfile(self._credentials_path(record_id)):
            self._problems[record_id] = {"code": "credentials_missing", "params": {}}
            return
        if location and self._is_volume():
            with self._lock:
                self._forget_volume(record_id)
            location = ""
            record = dict(record, path="")
        refusal = self._platform.prepare_mount_location(location=location)
        if refusal is not None:
            self._problems[record_id] = refusal
            self._stages.pop(record_id, None)
            return
        refusal = self._tooling_refusal()
        if refusal is not None:
            self._problems[record_id] = refusal
            self._stages.pop(record_id, None)
            return
        record = self._follow_entry(record_id, record)
        self._stages[record_id] = "mounting"
        self._on_change()
        try:
            share_url, port = self._share_target(record)
            attached_at = self._platform.attach_share(
                share_url=share_url,
                port=port,
                location=location,
                credentials_path=self._credentials_path(record_id),
            )
        except ShareAttachError as error:
            self._problems[record_id] = _share_refusal(error)
            self._stages.pop(record_id, None)
            self._log(f"could not mount {_share_url(record)}: {error.code}")
            # A refusal the person has to act on, a wrong password first
            # among them, is not retried on the timer: the record waits for
            # the login or the share to be changed. A host out of reach is
            # retried, since the network comes back on its own.
            if error.code in CLIENT_MOUNT_SETTLED_CODES:
                self._attached.discard(record_id)
                self._end_forward(record)
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
        if attached_at and attached_at != location:
            with self._lock:
                self._place_record(record_id, attached_at)
            location = attached_at
        self._problems.pop(record_id, None)
        self._stages.pop(record_id, None)
        self._log(f"mounted {_share_url(record)} at {location}")

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

        Args:
            record: The mount record.

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
            hub_id=hub_id, entry_id=entry_id, own_port=0, kind=self.service_type
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
                self._forget_volume(record_id)
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
        is_failed = record_id in self._problems or not os.path.isfile(
            self._credentials_path(record_id)
        )
        if not is_failed and record_id in self._attached:
            return False
        try:
            return not self._platform.is_share_attached(
                location=str(record.get("path", ""))
            )
        except PlatformUnsupportedError:
            return True

    def _drop_record(self, record_id: str) -> None:
        """Forget one record, its login and its standing; under the lock."""
        record = self._store.mounts().get(record_id)
        if record is not None:
            self._end_forward(record)
        self._discard_credentials(record_id)
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

    def _is_volume(self) -> bool:
        """Whether the system places a share's mount point itself."""
        return self._platform.mount_location_shape == MOUNT_SHAPE_VOLUME

    def _place_record(self, record_id: str, path: str) -> None:
        """Write a record's path back to the store; under the lock."""
        record = self._store.mounts().get(record_id)
        if record is not None and record.get("path") != path:
            self._store.set_mount(record_id, dict(record, path=path))

    def _forget_volume(self, record_id: str) -> None:
        """Empty a detached record's path where the system placed it; under the lock."""
        if self._is_volume():
            self._place_record(record_id, "")

    def _credentials_path(self, record_id: str) -> str:
        return os.path.join(self._credentials_dir, f"{record_id}.credentials")

    def _discard_credentials(self, record_id: str) -> None:
        try:
            os.unlink(self._credentials_path(record_id))
        except OSError:
            pass
