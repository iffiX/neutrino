"""``nclient file``: the machines' shares, mounted on this computer.

``list`` prints each machine's shares, a folder share once per account,
where each is mounted here and whether it is. ``mount`` is the Files page's **Mount**: a machine's share
takes its login from the hub and asks nothing, and a declared share asks
its user name and password at the terminal, never on the command line.
Both wait for the record to settle and print how it ended.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.cli import names, wording

# The record states of a mount at work, and of an unmount at work.
FILE_MOUNT_WORKING = ("pending", "queued", "mounting")
FILE_UNMOUNT_WORKING = ("unmounting",)
FILE_STATE_MOUNTED = "mounted"
FILE_STATE_FAILED = "failed"
# The refusals a declared share answers when its login is wrong.
FILE_LOGIN_CODES = (
    "share_login_rejected",
    "share_access_denied",
    "credentials_missing",
)


def main_list(*, hub: str = "") -> int:
    """Print each machine's shares: the share, where it is mounted, and how.

    Args:
        hub: What ``--hub`` named; empty lists every hub's.

    Returns:
        0, or 1 when the client does not answer or ``--hub`` names nothing.
    """
    state = wording.read_state()
    if state is None:
        return 1
    is_known, hub_id = names.scope(state, hub)
    if not is_known:
        return 1
    heading = None
    for entry in names.file_entries(state, hub_id):
        machine = names.machine_label(entry)
        if machine != heading:
            wording.say(machine)
            heading = machine
        record = _record(state, entry)
        place = str((record or {}).get("path", "") or "") or wording.line("none")
        wording.say(f"  {names.share_label(entry)}  {place}  {_standing(record)}")
    return 0


def main_mount(
    share: str, *, account: str = "", path: str = "", drive: str = "", hub: str = ""
) -> int:
    """Mount one share, as **Mount** does, at the place given or the default.

    Args:
        share: ``<machine>[/<share>]`` as ``list`` names it.
        account: The account a folder share is mounted as; empty where the
            share has one.
        path: The folder to mount it at, on Linux and macOS.
        drive: The drive letter to mount it as, on Windows.
        hub: What ``--hub`` named.

    Returns:
        0 once the share is mounted, 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = names.choose_share(state, share, hub, account)
    if entry is None:
        return 1
    record = _record(state, entry)
    if record is not None and record.get("state") == FILE_STATE_MOUNTED:
        wording.say(_placed(record))
        return 0
    place = path or drive
    body = _mount_body(entry, record, place)
    if body is None:
        return 1
    if wording.post("/api/services/file", body) is None:
        return 1
    fresh = wording.settled_state(_settled(entry, FILE_MOUNT_WORKING))
    if fresh is None:
        return 1
    return _report(fresh, entry)


def main_unmount(share: str, *, account: str = "", hub: str = "") -> int:
    """Unmount one share; its record stays for the next mount.

    Args:
        share: ``<machine>[/<share>]`` as ``list`` names it.
        account: The account a folder share is mounted as; empty where the
            share has one.
        hub: What ``--hub`` named.

    Returns:
        0 once the share is unmounted, or when it was not mounted, 1 for a
        refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    entry = names.choose_share(state, share, hub, account)
    if entry is None:
        return 1
    state = wording.settled_state(_settled(entry, FILE_MOUNT_WORKING))
    if state is None:
        return 1
    record = _record(state, entry)
    if record is None or record.get("state") != FILE_STATE_MOUNTED:
        if record is not None:
            wording.say(_placed(record))
        return 0
    body = {
        "action": "unmount",
        "hub_id": entry.get("hub_id", ""),
        "record_id": record.get("record_id", ""),
    }
    if wording.post("/api/services/file", body) is None:
        return 1
    fresh = wording.settled_state(_settled(entry, FILE_UNMOUNT_WORKING))
    if fresh is None:
        return 1
    return _report(fresh, entry)


def _mount_body(entry: dict, record: "dict | None", place: str) -> "dict | None":
    """What a mount sends: the record again, a new place, or a new login.

    Args:
        entry: The share's entry.
        record: Its mount record, None while it has none.
        place: The place given; empty takes the record's, else the default.

    Returns:
        The body, or None after the person gave no user name for a declared
        share.
    """
    hub_id = str(entry.get("hub_id", ""))
    is_declared = _is_declared(entry)
    if record is not None and not place:
        if is_declared and record.get("code") in FILE_LOGIN_CODES:
            login = _ask_login(entry)
            if login is None:
                return None
            return dict(
                login,
                action="set",
                hub_id=hub_id,
                record_id=record.get("record_id", ""),
            )
        return {
            "action": "mount",
            "hub_id": hub_id,
            "record_id": record.get("record_id", ""),
        }
    body = {
        "action": "mount",
        "hub_id": hub_id,
        "id": entry.get("id", ""),
        "path": place,
    }
    if is_declared:
        login = _ask_login(entry)
        if login is None:
            return None
        body.update(login)
    return body


def _ask_login(entry: dict) -> "dict | None":
    """A declared share's user name and password, asked at the terminal.

    Returns:
        ``{"username", "password"}``, or None after an empty user name.
    """
    share = names.share_name(entry)
    username = wording.ask_text(wording.line("ask_user", share=share))
    if not username:
        wording.say(wording.line("user_missing"), is_error=True)
        return None
    password = wording.ask_secret(wording.line("ask_password", share=share))
    return {"username": username, "password": password}


def _is_declared(entry: dict) -> bool:
    """Whether a share is a declared one, whose login the person types."""
    if "is_declared" in entry:
        return entry.get("is_declared") is True
    return entry.get("source") == "declared"


def _report(state: dict, entry: dict) -> int:
    """Print where a share stands after a mount or an unmount, and the status.

    Returns:
        1 when its record failed or its job ended in a failure, 0 otherwise.
    """
    row = next(
        (
            item
            for item in names.file_entries(state, str(entry.get("hub_id", "")))
            if item.get("id") == entry.get("id")
        ),
        {},
    )
    failure = wording.refusal_of(row.get("last_error") or {})
    record = _record(state, entry)
    if failure is None and record is not None and record.get("code"):
        failure = {"code": str(record["code"]), "params": record.get("params") or {}}
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    if record is not None:
        wording.say(_placed(record))
    return 0


def _settled(entry: dict, working: tuple):
    """The check that a share's record and its row are no longer at work."""

    def is_settled(state: dict) -> bool:
        record = _record(state, entry) or {}
        rows = names.file_entries(state, str(entry.get("hub_id", "")))
        is_job = any(row.get("job") for row in rows if row.get("id") == entry.get("id"))
        return record.get("state") not in working and not is_job

    return is_settled


def _record(state: dict, entry: dict) -> "dict | None":
    """A share's mount record, the mounted one first; None while it has none."""
    records = [
        record
        for record in state.get("mounts") or []
        if isinstance(record, dict)
        and record.get("hub_id") == entry.get("hub_id")
        and record.get("entry_id") == entry.get("id")
    ]
    mounted = [
        record for record in records if record.get("state") == FILE_STATE_MOUNTED
    ]
    records = mounted + [record for record in records if record not in mounted]
    return records[0] if records else None


def _standing(record: "dict | None") -> str:
    """How a share stands here: its record's state, or its failure's words."""
    if record is None:
        return wording.word_mount_state("detached")
    if record.get("code"):
        return wording.word_code(str(record["code"]), record.get("params"))
    return wording.word_mount_state(str(record.get("state", ""))) or (
        wording.word_mount_state(
            FILE_STATE_MOUNTED if record.get("is_attached") else "detached"
        )
    )


def _placed(record: dict) -> str:
    """``<place>: <standing>``, one colon after a drive letter as after a path."""
    place = str(record.get("path", "") or "")
    label = place if place.endswith(":") else f"{place}:"
    return f"{label} {_standing(record)}"
