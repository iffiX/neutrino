"""The mounts service: attaching published shares where a person asks.

The form asks for the share's own username, password and a path; the
password becomes a root-only credentials file on this machine and never
travels to the hub. An ordinary identity may attach only where its account
can write, judged as that account; a privileged one anywhere. A path under
the asking account's home is ownership-mapped to that account; anywhere
else follows the share's own permissions.

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
import time

from neutrino_agent.constants import (
    AGENT_MOUNT_CREDENTIALS_DIR,
    AGENT_MOUNT_RECHECK_INTERVAL_S,
)
from neutrino_agent.platforms.base import PlatformUnsupportedError, ShareAttachError

MOUNT_RECORD_ID_LENGTH = 16


def mount_record_id(offer_id: str, location: str) -> str:
    """The stable id one attachment is kept under.

    Args:
        offer_id: The offer attached.
        location: The mount point.

    Returns:
        A short hex id; the same offer at the same path is the same record.
    """
    digest = hashlib.sha256(f"{offer_id}\n{location}".encode("utf-8"))
    return digest.hexdigest()[:MOUNT_RECORD_ID_LENGTH]


def _share_url(record: dict) -> str:
    return f"//{record.get('host', '')}/{record.get('share', '')}"


def _share_refusal(error: ShareAttachError) -> dict:
    params = {"detail": error.detail} if error.detail else {}
    return {"code": error.code, "params": params}


class MountsService:
    """Attaches, detaches, reports and remounts this machine's share mounts."""

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

    def attach(
        self,
        *,
        account: str,
        is_privileged: bool,
        offer_id: str,
        offer: dict,
        username: str,
        password: str,
        path: str,
    ) -> dict:
        """Attach one published share at a path.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            offer_id: The offer's id in the catalog.
            offer: The offer, naming the host and share.
            username: The share's own username.
            password: The share's own password; it stays on this machine.
            path: The mount point.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if not path or not os.path.isabs(path):
            return {"code": "fs_refused", "params": {}}
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
            record_id = mount_record_id(offer_id, location)
            record = {
                "offer_id": offer_id,
                "host": str(offer.get("host", "")),
                "share": str(offer.get("share", "")),
                "username": username,
                "path": location,
                "account": account,
                "is_enabled": True,
            }
            try:
                self._platform.attach_share(
                    account=account,
                    share_url=_share_url(record),
                    username=username,
                    password=password,
                    location=location,
                    credentials_path=self._credentials_path(record_id),
                )
            except ShareAttachError as error:
                self._discard_credentials(record_id)
                return _share_refusal(error)
            except PlatformUnsupportedError:
                return {"code": "unsupported_platform", "params": {}}
            self._store.set_mount(record_id, record)
            self._problems.pop(record_id, None)
            self._log(f"mounted {_share_url(record)} at {location}")
            return {}

    def detach(self, *, account: str, is_privileged: bool, record_id: str) -> dict:
        """Detach one attachment: unmount, drop the credentials, drop the record.

        Args:
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            record_id: The record to detach.

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
            self._discard_credentials(record_id)
            self._store.remove_mount(record_id)
            self._problems.pop(record_id, None)
            self._log(f"unmounted {location}")
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
            rows.append(
                {
                    "record_id": record_id,
                    "offer_id": record.get("offer_id", ""),
                    "host": record.get("host", ""),
                    "share": record.get("share", ""),
                    "username": record.get("username", ""),
                    "path": location,
                    "account": record.get("account", ""),
                    "is_enabled": bool(record.get("is_enabled")),
                    "is_attached": is_attached,
                    "code": problem.get("code", ""),
                    "params": problem.get("params", {}),
                }
            )
        return rows

    def reconcile(self) -> None:
        """Remount every enabled record that is not attached."""
        with self._lock:
            for record_id, record in sorted(self._store.mounts().items()):
                if not record.get("is_enabled"):
                    continue
                self._remount(record_id, record)

    def start(self) -> None:
        """Reconcile now and keep reconciling on a timer."""
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                self.reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"mount reconcile crashed: {error}")
            time.sleep(AGENT_MOUNT_RECHECK_INTERVAL_S)

    def _remount(self, record_id: str, record: dict) -> None:
        location = str(record.get("path", ""))
        try:
            if self._platform.is_share_attached(location=location):
                self._problems.pop(record_id, None)
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
            return
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
            return
        except PlatformUnsupportedError:
            return
        self._problems.pop(record_id, None)
        self._log(f"remounted {_share_url(record)} at {location}")

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
