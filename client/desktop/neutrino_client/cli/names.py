"""How a person names a hub, a machine, an app, a share or a session.

A name is what ``list`` prints. A hub is named by its name, its id or its
number in ``hub list``, and ``--hub`` narrows every other lookup to one hub.
An app two machines hold under one name is ``<machine>/<app>``, and a share
is ``<machine>/<share>``, its share left out where the machine has one. A
name that matches nothing prints the names there are; one that matches
several prints the full names, and the caller exits.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import re

from neutrino_client.cli import wording
from neutrino_client.services.app import APP_ENTRY_KINDS
from neutrino_client.services.ssh import ssh_machines

# The suffix of every local name, and of the host ssh is given.
LOCAL_NAME_SUFFIX = ".localhost"
SSH_HOST_SUFFIX = ".nt"
# What the slug rule keeps, and how long a slug grows.
SLUG_OUTSIDE = re.compile(r"[^a-z0-9]+")
SLUG_LENGTH_MAX = 63


def slug(text: str, fallback: str = "machine") -> str:
    """A name as a local name spells it.

    Args:
        text: The name.
        fallback: What an empty slug reads as.

    Returns:
        The text in lowercase, each run of characters other than a to z and
        0 to 9 one ``-``, ``-`` taken off both ends, at most 63 characters.
    """
    cut = SLUG_OUTSIDE.sub("-", str(text).lower()).strip("-")[:SLUG_LENGTH_MAX]
    return cut.strip("-") or fallback


def hub_rows(state: dict) -> list:
    """The hubs the state lists, in the order joined."""
    return [row for row in state.get("hubs") or [] if isinstance(row, dict)]


def scope(state: dict, hub: str) -> "tuple[bool, str]":
    """The hub ``--hub`` narrows a lookup to.

    Args:
        state: The state payload.
        hub: What ``--hub`` named; empty narrows nothing.

    Returns:
        ``(is_known, hub_id)``: False after the refusal was printed; an
        empty id narrows nothing.
    """
    if not hub:
        return True, ""
    row = wording.choose_hub(hub_rows(state), hub)
    if row is None:
        return False, ""
    return True, str(row.get("hub_id", ""))


def entries(state: dict, kind: str = "", hub_id: str = "") -> list:
    """The published entries of one kind, in the state's order.

    Args:
        state: The state payload.
        kind: The entry type; empty keeps every type.
        hub_id: Keep only one hub's entries; empty keeps every hub's.

    Returns:
        The entries.
    """
    rows = [row for row in state.get("services") or [] if isinstance(row, dict)]
    if kind:
        rows = [row for row in rows if row.get("type") == kind]
    if hub_id:
        rows = [row for row in rows if row.get("hub_id") == hub_id]
    return rows


def apps(state: dict, hub_id: str = "") -> list:
    """The apps the state lists, in its order, the machine's SSH server among them.

    Args:
        state: The state payload.
        hub_id: Keep only one hub's apps; empty keeps every hub's.

    Returns:
        The apps.
    """
    rows = [row for row in state.get("apps") or [] if isinstance(row, dict)]
    if hub_id:
        rows = [row for row in rows if row.get("hub_id") == hub_id]
    return rows


def shown_apps(state: dict, hub_id: str = "") -> list:
    """The apps the Apps page shows, in the state's order.

    Args:
        state: The state payload.
        hub_id: Keep only one hub's apps; empty keeps every hub's.

    Returns:
        The apps with a ``web`` or ``port`` entry; the machine's SSH server
        and an app of ``file`` entries alone are not among them.
    """
    return [app for app in apps(state, hub_id) if app_entries(state, app)]


def app_entries(state: dict, app: dict) -> list:
    """One app's entries the Apps page shows, in the hub's order.

    Args:
        state: The state payload.
        app: The app.

    Returns:
        Its ``web`` and ``port`` entries.
    """
    return [
        row
        for row in entries(state, hub_id=str(app.get("hub_id", "")))
        if row.get("app_id") == app.get("id") and row.get("type") in APP_ENTRY_KINDS
    ]


def app_name(app: dict) -> str:
    """What ``app list`` calls one app: its local name's first label.

    Args:
        app: The app.

    Returns:
        The name, or the slug of its title when it has no local name.
    """
    local_name = str(app.get("local_name", "") or "")
    if local_name:
        return local_name.split(".", 1)[0]
    return slug(str(app.get("title", "")), "app")


def app_machine(app: dict) -> str:
    """The machine part of one app's local name.

    Args:
        app: The app.

    Returns:
        The machine's slug, as the local name spells it.
    """
    local_name = str(app.get("local_name", "") or "")
    labels = local_name[: -len(LOCAL_NAME_SUFFIX)].split(".")
    if local_name.endswith(LOCAL_NAME_SUFFIX) and len(labels) >= 2:
        return labels[1]
    return slug(str(app.get("device_name", "")))


def machine_label(row: dict) -> str:
    """What a list calls the machine an entry or an app is on.

    Args:
        row: An entry or an app.

    Returns:
        Its device name, else its address, else its local name's machine.
    """
    name = str(row.get("device_name", "") or "")
    if name:
        return name
    host = str((row.get("payload") or {}).get("host", "") or "")
    return host or app_machine(row)


def choose(what: str, needle: str, candidates: list) -> "dict | None":
    """The one candidate a name means.

    Args:
        what: The line key of what is named, such as ``what_app``.
        needle: What the person typed.
        candidates: ``(names, full, item)`` per candidate: the names that
            mean it, compared without case; the name printed when several
            match; and the item.

    Returns:
        The item, or None after the refusal was printed.
    """
    folded = needle.lower()
    matches = [
        (full, item)
        for names, full, item in candidates
        if folded in {str(name).lower() for name in names if name}
    ]
    unique = {id(item): (full, item) for full, item in matches}
    if len(unique) == 1:
        return next(iter(unique.values()))[1]
    if not unique:
        listed = []
        for _names, full, _item in candidates:
            if full not in listed:
                listed.append(full)
        wording.unknown_name(what, needle, listed)
        return None
    wording.ambiguous_name(what, needle, sorted({full for full, _item in matches}))
    return None


def choose_app(state: dict, needle: str, hub: str = "") -> "dict | None":
    """The one app a name means.

    Args:
        state: The state payload.
        needle: The app's name, its title, its id, or ``<machine>/<app>``.
        hub: What ``--hub`` named.

    Returns:
        The app, or None after the refusal was printed.
    """
    is_known, hub_id = scope(state, hub)
    if not is_known:
        return None
    candidates = []
    for app in shown_apps(state, hub_id):
        name = app_name(app)
        machines = {app_machine(app), str(app.get("device_name", "") or "")}
        full = f"{app_machine(app)}/{name}"
        names = {name, str(app.get("title", "")), str(app.get("id", "")), full}
        names |= {f"{machine}/{name}" for machine in machines if machine}
        candidates.append((names, full, app))
    return choose("what_app", needle, candidates)


def file_entries(state: dict, hub_id: str = "") -> list:
    """The shares the state lists, in its order."""
    return entries(state, "file", hub_id)


def share_name(entry: dict) -> str:
    """What ``file list`` calls one share: its share name."""
    payload = entry.get("payload") or {}
    return str(payload.get("share", "") or entry.get("name", "") or "")


def choose_share(state: dict, needle: str, hub: str = "") -> "dict | None":
    """The one share a name means.

    Args:
        state: The state payload.
        needle: ``<machine>/<share>``, or ``<machine>`` for a machine with
            one share.
        hub: What ``--hub`` named.

    Returns:
        The share's entry, or None after the refusal was printed.
    """
    is_known, hub_id = scope(state, hub)
    if not is_known:
        return None
    shares = file_entries(state, hub_id)
    machine, _, share = needle.partition("/")
    on_machine = [
        entry
        for entry in shares
        if machine.lower()
        in (
            machine_label(entry).lower(),
            str(entry.get("device_id", "")).lower(),
            slug(machine_label(entry)),
        )
    ]
    if not share and len(on_machine) > 1:
        wording.ambiguous_name(
            "what_share",
            needle,
            [f"{machine_label(entry)}/{share_name(entry)}" for entry in on_machine],
        )
        return None
    if not share and len(on_machine) == 1:
        return on_machine[0]
    candidates = [
        (
            {f"{machine_label(entry)}/{share_name(entry)}"}
            | {
                f"{name}/{share_name(entry)}"
                for name in (
                    str(entry.get("device_id", "")),
                    slug(machine_label(entry)),
                )
            },
            f"{machine_label(entry)}/{share_name(entry)}",
            entry,
        )
        for entry in shares
    ]
    return choose("what_share", needle, candidates)


def terminal_machines(state: dict, hub_id: str = "") -> list:
    """The machines the state offers a terminal on, in its order."""
    machines = [
        row
        for row in (state.get("terminals") or {}).get("machines") or []
        if isinstance(row, dict)
    ]
    if hub_id:
        machines = [row for row in machines if row.get("hub_id") == hub_id]
    return machines


def choose_terminal_machine(state: dict, needle: str, hub: str = "") -> "dict | None":
    """The one machine a terminal command names.

    Args:
        state: The state payload.
        needle: The machine's name or id.
        hub: What ``--hub`` named.

    Returns:
        The machine, or None after the refusal was printed; a name two hubs
        hold asks for ``--hub``.
    """
    is_known, hub_id = scope(state, hub)
    if not is_known:
        return None
    machines = terminal_machines(state, hub_id)
    matches = [
        row
        for row in machines
        if needle.lower()
        in (str(row.get("name", "")).lower(), str(row.get("device_id", "")).lower())
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        wording.unknown_name(
            "what_machine", needle, [str(row.get("name", "")) for row in machines]
        )
        return None
    hubs = {row.get("hub_id") for row in matches}
    names = ", ".join(
        wording.hub_name(row) for row in hub_rows(state) if row.get("hub_id") in hubs
    )
    wording.refuse("ambiguous_hub", {"hubs": names})
    return None


def choose_rdp(state: dict, needle: str, hub: str = "") -> "dict | None":
    """The one shared desktop a machine's name means.

    Args:
        state: The state payload.
        needle: The machine's name.
        hub: What ``--hub`` named.

    Returns:
        The ``rdp`` entry, or None after the refusal was printed.
    """
    is_known, hub_id = scope(state, hub)
    if not is_known:
        return None
    candidates = [
        (
            {
                machine_label(entry),
                str(entry.get("title", "")),
                str(entry.get("device_id", "")),
            },
            machine_label(entry),
            entry,
        )
        for entry in entries(state, "rdp", hub_id)
    ]
    return choose("what_machine", needle, candidates)


def session_rows(state: dict, machine: dict) -> list:
    """The sessions the state lists on one machine."""
    return [
        row
        for row in (state.get("terminals") or {}).get("sessions") or []
        if isinstance(row, dict)
        and row.get("hub_id") == machine.get("hub_id")
        and row.get("device_id") == machine.get("device_id")
    ]


def choose_session(state: dict, machine: dict, prefix: str) -> "dict | None":
    """The one session whose id starts with a prefix, as git matches a commit.

    Args:
        state: The state payload.
        machine: The machine the session is on.
        prefix: The id's first characters.

    Returns:
        The session, or None after the refusal was printed: ``session_unknown``
        for no match, every candidate for several.
    """
    matches = [
        row
        for row in session_rows(state, machine)
        if prefix and str(row.get("session_id", "")).startswith(prefix)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        wording.refuse("session_unknown", {"session_id": prefix})
        return None
    wording.say(
        wording.line(
            "session_ambiguous", prefix=prefix, machine=machine.get("name", "")
        ),
        is_error=True,
    )
    for row in matches:
        wording.say(
            f"  {row.get('session_id', '')}  {row.get('title', '')}".rstrip(),
            is_error=True,
        )
    return None


def ssh_hosts(state: dict) -> list:
    """Every machine reached by ssh, as ``~/.ssh/neutrino_config`` names it.

    The host is the machine part of the machine's apps' local names; two
    hubs holding a machine of one slug give each ``<machine>.<hub>``, the
    hub's name by the same slug.

    Args:
        state: The state payload.

    Returns:
        ``[{host, hub_id, device_id, name, accounts, entries}]`` in the
        state's order, ``accounts`` the enabled accounts in the hub's order,
        the first the default, and ``entries`` the ``ssh`` entry of each.
    """
    hub_names = {
        str(row.get("hub_id", "")): wording.hub_name(row) for row in hub_rows(state)
    }
    return ssh_machines(entries(state, "ssh"), apps(state), hub_names)


def choose_ssh(state: dict, needle: str, hub: str = "") -> "tuple | None":
    """The machine and the ``ssh`` entry ``[<account>@]<machine>[.nt]`` names.

    Args:
        state: The state payload.
        needle: What the person or ssh gave.
        hub: What ``--hub`` named.

    Returns:
        ``(machine, entry)``: the machine as :func:`ssh_hosts` gives it and
        the account's entry, the first account's when none is named; None
        after the refusal was printed.
    """
    is_known, hub_id = scope(state, hub)
    if not is_known:
        return None
    account, _, machine_name = needle.rpartition("@")
    if machine_name.endswith(SSH_HOST_SUFFIX):
        machine_name = machine_name[: -len(SSH_HOST_SUFFIX)]
    machines = [
        row for row in ssh_hosts(state) if not hub_id or row["hub_id"] == hub_id
    ]
    candidates = [
        (
            {row["host"], row["name"], row["device_id"], f"{row['host']}.nt"},
            row["host"],
            row,
        )
        for row in machines
    ]
    machine = choose("what_machine", machine_name, candidates)
    if machine is None:
        return None
    if not account:
        return machine, machine["entries"][0]
    for name, entry in zip(machine["accounts"], machine["entries"]):
        if name == account:
            return machine, entry
    wording.unknown_name("what_account", account, machine["accounts"])
    return None
