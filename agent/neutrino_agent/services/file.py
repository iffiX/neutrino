"""The file service type: mounting published shares where a person asks.

Config asks for the share's own username, password and a path; the password
becomes a root-only credentials file on this machine and never travels to
the hub. Mount attaches, Unmount detaches. An ordinary identity may mount
only where its account can write, judged as that account; a privileged one
anywhere. A path under the asking account's home is ownership-mapped to that
account; anywhere else follows the share's own permissions.

The mount tooling is the ``samba_mount`` module's; nothing here installs it.
A mount asked for while the module is absent is refused with
``module_missing``, and the page's own notice says which module to install.

Records are machine state in the store; the reconcile remounts enabled
records that are not attached, which is what brings mounts back after a
reboot. A record whose credentials file is gone reports
``credentials_missing`` and waits for the password to be entered again.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import os
import threading

from neutrino_agent.constants import (
    AGENT_MOUNT_CREDENTIALS_DIR,
    AGENT_MOUNT_MODULE_NAME,
    AGENT_MOUNT_RECHECK_INTERVAL_S,
)
from neutrino_agent.platforms.base import PlatformUnsupportedError, ShareAttachError
from neutrino_agent.services.base import ServiceTypeHandler, find_entry

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


class FileServiceHandler(ServiceTypeHandler):
    """Mounts, unmounts, reports and remounts this machine's shares."""

    service_type = "file"

    def __init__(self, *, platform, store, credentials_dir: str = "", log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            store: The :class:`~neutrino_agent.services.store.MachineServiceStore`.
            credentials_dir: Where the per-record credentials files live;
                empty uses the agent's own.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._store = store
        self._credentials_dir = credentials_dir or AGENT_MOUNT_CREDENTIALS_DIR
        self._log = log
        self._lock = threading.Lock()
        self._problems: dict = {}
        # Live step per record: queued, mounting.
        self._stages: dict = {}
        self._wakeup = threading.Event()

    def act(self, *, entries: list, account: str, is_privileged: bool, body: dict):
        """Mount a share with the staged config, or unmount one record.

        Args:
            entries: The catalog's service list.
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            body: ``{"action": "mount", "id", "username", "password",
                "path"}`` for a fresh or reconfigured mount,
                ``{"action": "mount", "record_id"}`` to remount with the
                kept credentials, or ``{"action": "unmount", "record_id"}``
                — the record and its credentials stay, and a new Config
                submit replaces them.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        action = str(body.get("action", ""))
        if action == "mount" and body.get("record_id"):
            return self.remount(
                account=account,
                is_privileged=is_privileged,
                record_id=str(body.get("record_id", "")),
            )
        if action == "mount":
            entry = find_entry(entries, self.service_type, str(body.get("id", "")))
            if entry is None:
                return {"code": "unknown_request", "params": {}}
            return self.attach(
                account=account,
                is_privileged=is_privileged,
                entry_id=str(body.get("id", "")),
                payload=entry.get("payload") or {},
                username=str(body.get("username", "")),
                password=str(body.get("password", "")),
                path=str(body.get("path", "")),
            )
        if action == "unmount":
            return self.detach(
                account=account,
                is_privileged=is_privileged,
                record_id=str(body.get("record_id", "")),
            )
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """This machine's mount records with where each stands.

        Returns:
            ``{"mounts": [rows]}``; passwords appear nowhere.
        """
        return {"mounts": self.rows()}

    def start(self) -> None:
        """Reconcile now and keep reconciling on a timer."""
        threading.Thread(target=self._run, daemon=True).start()

    def attach(
        self,
        *,
        account: str,
        is_privileged: bool,
        entry_id: str,
        payload: dict,
        username: str,
        password: str,
        path: str,
    ) -> dict:
        """Mount one published share at a path.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            entry_id: The entry's id in the service list.
            payload: The entry's payload, naming the host and share.
            username: The share's own username.
            password: The share's own password; it stays on this machine.
            path: The mount point.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if not path or not os.path.isabs(path):
            return {"code": "fs_refused", "params": {}}
        refusal = self._tooling_refusal()
        if refusal is not None:
            return refusal
        location = os.path.abspath(path)
        with self._lock:
            if not is_privileged:
                try:
                    if not self._platform.is_path_writable(
                        account=account, path=location
                    ):
                        return {"code": "fs_refused", "params": {}}
                except PlatformUnsupportedError:
                    return {"code": "unsupported_platform", "params": {}}
            refusal = self._prepare_mount_point(
                account="" if is_privileged else account, location=location
            )
            if refusal is not None:
                return refusal
            for old_id, old in list(self._store.mounts().items()):
                if old.get("entry_id") != entry_id:
                    continue
                try:
                    if self._platform.is_share_attached(
                        location=str(old.get("path", ""))
                    ):
                        self._platform.detach_share(location=str(old.get("path", "")))
                except (ShareAttachError, PlatformUnsupportedError):
                    pass
                self._discard_credentials(old_id)
                self._store.remove_mount(old_id)
                self._problems.pop(old_id, None)
                self._stages.pop(old_id, None)
            record_id = mount_record_id(entry_id, location)
            record = {
                "entry_id": entry_id,
                "host": str(payload.get("host", "")),
                "share": str(payload.get("share", "")),
                "username": username,
                "path": location,
                "account": account,
                "is_enabled": True,
            }
            try:
                self._platform.write_share_credentials(
                    credentials_path=self._credentials_path(record_id),
                    username=username,
                    password=password,
                )
            except PlatformUnsupportedError:
                return {"code": "unsupported_platform", "params": {}}
            # Queued, not mounted: the mount can take a while, and the page
            # reads the step from the rows rather than this call hanging on
            # it.
            self._store.set_mount(record_id, record)
            self._problems.pop(record_id, None)
            self._stages[record_id] = "queued"
            self._log(f"queued {_share_url(record)} for {location}")
        self._wakeup.set()
        return {}

    def remount(self, *, account: str, is_privileged: bool, record_id: str) -> dict:
        """Mount a kept record again with the credentials it saved.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
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
            if not is_privileged and record.get("account") != account:
                return {"code": "control_scope_refused", "params": {}}
            record = dict(record)
            record["is_enabled"] = True
            self._store.set_mount(record_id, record)
            self._problems.pop(record_id, None)
            self._stages[record_id] = "queued"
            self._log(f"queued {_share_url(record)} again")
        self._wakeup.set()
        return {}

    def detach(self, *, account: str, is_privileged: bool, record_id: str) -> dict:
        """Unmount one record; the record and its credentials are kept.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            record_id: The record to unmount.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        with self._lock:
            record = self._store.mounts().get(record_id)
            if record is None:
                return {"code": "unknown_request", "params": {}}
            if not is_privileged and record.get("account") != account:
                return {"code": "control_scope_refused", "params": {}}
            location = str(record.get("path", ""))
            try:
                if self._platform.is_share_attached(location=location):
                    self._platform.detach_share(location=location)
            except ShareAttachError as error:
                return _share_refusal(error)
            except PlatformUnsupportedError:
                return {"code": "unsupported_platform", "params": {}}
            record = dict(record)
            record["is_enabled"] = False
            self._store.set_mount(record_id, record)
            self._problems.pop(record_id, None)
            self._stages.pop(record_id, None)
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
            elif record.get("is_enabled"):
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
                    "account": record.get("account", ""),
                    "is_enabled": bool(record.get("is_enabled")),
                    "is_attached": is_attached,
                    "state": state,
                    "code": problem.get("code", ""),
                    "params": problem.get("params", {}),
                }
            )
        return rows

    def reconcile(self) -> None:
        """Remount every enabled record that is not attached.

        The snapshot is taken under the lock and the mounting done outside
        it: a mount can take a while, and the control channel must go on
        answering while it does. A record detached mid-step is re-checked
        by the next pass rather than raced here.
        """
        with self._lock:
            pending = sorted(self._store.mounts().items())
        for record_id, record in pending:
            if not record.get("is_enabled"):
                continue
            self._remount(record_id, record)

    def _run(self) -> None:
        while True:
            try:
                self.reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"mount reconcile crashed: {error}")
            self._wakeup.wait(timeout=AGENT_MOUNT_RECHECK_INTERVAL_S)
            self._wakeup.clear()

    def _remount(self, record_id: str, record: dict) -> None:
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
        account = str(record.get("account", ""))
        refusal = self._prepare_mount_point(
            account="" if account == "root" else account, location=location
        )
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
        try:
            self._platform.attach_share(
                account=account,
                share_url=_share_url(record),
                username=str(record.get("username", "")),
                password="",
                location=location,
                credentials_path=self._credentials_path(record_id),
            )
        except ShareAttachError as error:
            self._problems[record_id] = _share_refusal(error)
            self._stages.pop(record_id, None)
            return
        except PlatformUnsupportedError:
            self._stages.pop(record_id, None)
            return
        self._problems.pop(record_id, None)
        self._stages.pop(record_id, None)
        self._log(f"mounted {_share_url(record)} at {location}")

    def _tooling_refusal(self) -> "dict | None":
        """Refuse when the mount tooling the samba_mount module owns is absent.

        Returns:
            None when mounting can go ahead, the typed refusal otherwise.
        """
        try:
            is_ready = self._platform.has_mount_tooling()
        except PlatformUnsupportedError:
            is_ready = True
        if is_ready:
            return None
        return {
            "code": "module_missing",
            "params": {"module": AGENT_MOUNT_MODULE_NAME},
        }

    def _prepare_mount_point(self, *, account: str, location: str) -> "dict | None":
        """Have the mount point be an empty directory, creating it as the
        account when it is not there.

        Args:
            account: Whose identity creates a missing directory; empty
                creates as the agent itself.
            location: The mount point.

        Returns:
            None when the point is ready, a refusal otherwise.
        """
        if os.path.exists(location):
            if not os.path.isdir(location):
                return {"code": "mountpoint_not_empty", "params": {}}
            try:
                if os.listdir(location):
                    return {"code": "mountpoint_not_empty", "params": {}}
            except OSError:
                return {"code": "fs_refused", "params": {}}
            return None
        try:
            self._platform.make_directory(account=account, path=location)
        except (OSError, PlatformUnsupportedError):
            return {"code": "fs_refused", "params": {}}
        return None

    def _credentials_path(self, record_id: str) -> str:
        return os.path.join(self._credentials_dir, f"{record_id}.credentials")

    def _discard_credentials(self, record_id: str) -> None:
        try:
            os.unlink(self._credentials_path(record_id))
        except OSError:
            pass
