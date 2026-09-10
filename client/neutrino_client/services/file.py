"""The file service type: mounting published shares where the person asks.

Config asks for the share's own username, password and a path; the password
becomes a credentials file only this person reads and never travels to the
hub. Mount attaches, Unmount detaches. The privileged part of a mount is the
platform's: on Linux it goes through the root helper under ``pkexec``.

A record in the store is the login and the path this person typed, nothing
more: what is attached is this run's own. The reconcile remounts what this
run attached and lost, which is what brings a share back after the network
dropped; a record from an earlier run waits for the person to ask. A record
whose credentials file is gone reports ``credentials_missing`` and waits for
the password to be entered again.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hashlib
import os
import threading

from neutrino_client.constants import CLIENT_MOUNT_RECHECK_INTERVAL_S
from neutrino_client.exceptions import PlatformUnsupportedError, ShareAttachError
from neutrino_client.services.base import ServiceTypeHandler, find_entry

MOUNT_RECORD_ID_LENGTH = 16


def mount_record_id(entry_id: str, location: str) -> str:
    """The stable id one mount is kept under.

    Args:
        entry_id: The service entry mounted.
        location: The mount point.

    Returns:
        A short hex id; the same entry at the same path is the same record.
    """
    digest = hashlib.sha256(f"{entry_id}\n{location}".encode("utf-8"))
    return digest.hexdigest()[:MOUNT_RECORD_ID_LENGTH]


def _share_url(record: dict) -> str:
    return f"//{record.get('host', '')}/{record.get('share', '')}"


def _share_refusal(error: ShareAttachError) -> dict:
    params = {"detail": error.detail} if error.detail else {}
    return {"code": error.code, "params": params}


def _nobody() -> None:
    """Nobody listening for changes."""


class FileServiceHandler(ServiceTypeHandler):
    """Mounts, unmounts, reports and remounts this person's shares."""

    service_type = "file"

    def __init__(
        self, *, platform, store, credentials_dir: str, log=print, on_change=None
    ):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            credentials_dir: Where the per-record credentials files live.
            log: Callable used for progress messages.
            on_change: Called after every change a record's row would show;
                None for nobody listening.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir
        self._log = log
        self._on_change = on_change if on_change is not None else _nobody
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
            entries: The catalog's service list.
            body: ``{"action": "mount", "id", "username", "password",
                "path"}`` for a fresh or reconfigured mount,
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
            entry = find_entry(entries, self.service_type, str(body.get("id", "")))
            if entry is None:
                return {"code": "unknown_request", "params": {}}
            return self.attach(
                entry_id=str(body.get("id", "")),
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
        detached = 0
        with self._lock:
            self._attached = set()
            for record_id, record in sorted(self._store.mounts().items()):
                location = str(record.get("path", ""))
                try:
                    if self._platform.is_share_attached(location=location):
                        self._platform.detach_share(location=location)
                        detached += 1
                except (ShareAttachError, PlatformUnsupportedError) as error:
                    self._log(f"could not unmount {location}: {error}")
                self._stages.pop(record_id, None)
        return detached

    def clear_leftovers(self) -> None:
        """Detach every record an earlier run left attached."""
        with self._lock:
            records = sorted(self._store.mounts().items())
        for _record_id, record in records:
            location = str(record.get("path", ""))
            try:
                if not self._platform.is_share_attached(location=location):
                    continue
                self._platform.detach_share(location=location)
            except (ShareAttachError, PlatformUnsupportedError) as error:
                self._log(f"could not unmount {location}: {error}")
                continue
            self._log(f"unmounted {location} after an unclean exit")

    def attach(
        self,
        *,
        entry_id: str,
        payload: dict,
        username: str,
        password: str,
        path: str,
    ) -> dict:
        """Mount one published share at a path.

        Args:
            entry_id: The entry's id in the service list.
            payload: The entry's payload, naming the host and share.
            username: The share's own username.
            password: The share's own password; it stays on this machine.
            path: The mount point.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        refusal = self._platform.validate_mount_location(location=path)
        if refusal is not None:
            return refusal
        refusal = self._tooling_refusal()
        if refusal is not None:
            return refusal
        location = os.path.normpath(path)
        with self._lock:
            refusal = self._platform.prepare_mount_location(location=location)
            if refusal is not None:
                return refusal
            for old_id, old in list(self._store.mounts().items()):
                if old.get("entry_id") != entry_id:
                    continue
                old_location = str(old.get("path", ""))
                try:
                    if self._platform.is_share_attached(location=old_location):
                        self._platform.detach_share(location=old_location)
                except (ShareAttachError, PlatformUnsupportedError):
                    pass
                self._discard_credentials(old_id)
                self._store.remove_mount(old_id)
                self._problems.pop(old_id, None)
                self._stages.pop(old_id, None)
                self._attached.discard(old_id)
            record_id = mount_record_id(entry_id, location)
            record = {
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
            self._log(f"queued {_share_url(record)} for {location}")
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
            self._problems.pop(record_id, None)
            self._stages.pop(record_id, None)
            self._attached.discard(record_id)
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
                    "entry_id": record.get("entry_id", ""),
                    "host": record.get("host", ""),
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
        self._stages[record_id] = "mounting"
        self._on_change()
        try:
            self._platform.attach_share(
                share_url=_share_url(record),
                location=location,
                credentials_path=self._credentials_path(record_id),
            )
        except ShareAttachError as error:
            self._problems[record_id] = _share_refusal(error)
            self._stages.pop(record_id, None)
            # A declined authorization is not retried on the timer: the
            # record waits for the person to ask again.
            if error.code == "mount_not_authorized":
                self._attached.discard(record_id)
            return
        except PlatformUnsupportedError:
            self._stages.pop(record_id, None)
            return
        self._problems.pop(record_id, None)
        self._stages.pop(record_id, None)
        self._log(f"mounted {_share_url(record)} at {location}")

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

    def _credentials_path(self, record_id: str) -> str:
        return os.path.join(self._credentials_dir, f"{record_id}.credentials")

    def _discard_credentials(self, record_id: str) -> None:
        try:
            os.unlink(self._credentials_path(record_id))
        except OSError:
            pass
