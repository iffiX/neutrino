"""``nclient app``: the apps the hubs publish, from a terminal.

``list`` prints each machine's apps with every entry's kind and local
address, which are fixed, so they show before the app is used. ``use`` is
the Apps page's **Use**, ``open`` its **Open**, ``stop`` its **Stop** and
``set`` its **Configure**; ``use`` and ``open`` wait for the job they start
and print how it ended.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import urllib.parse

from neutrino_client.cli import names, wording

# The host every local address opens on where the browser resolves no
# ``.localhost`` name.
APP_LOOPBACK_HOST = "127.0.0.1"
APP_LOOPBACK_OS = "darwin"
# The separator of ``--port``'s entry and number.
APP_PORT_SEPARATOR = "="
# The line an app's use reads, by whether it is in use.
APP_USE_LINES = {True: "in_use", False: "not_in_use"}


def main_list(*, hub: str = "") -> int:
    """Print each machine's apps, their entries and local addresses.

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
    is_several_hubs = len(names.hub_rows(state)) > 1 and not hub_id
    hub_names = {
        row.get("hub_id"): wording.hub_name(row) for row in names.hub_rows(state)
    }
    heading = None
    for app in names.apps(state, hub_id):
        machine = names.machine_label(app)
        if is_several_hubs:
            machine = f"{machine} ({hub_names.get(app.get('hub_id'), '')})"
        if machine != heading:
            wording.say(machine)
            heading = machine
        use = wording.line(APP_USE_LINES[app.get("is_in_use") is True])
        source = wording.line(f"source_{app.get('source', '')}")
        wording.say(f"  {names.app_name(app)}  {source}  {use}")
        for entry in names.app_entries(state, app):
            kind = wording.line(f"kind_{entry.get('type', '')}")
            address = local_address(state, app, entry)
            tail = f"  ({wording.line('unhealthy')})" if _is_unhealthy(entry) else ""
            line = f"    {entry.get('name', '')}  {kind}"
            wording.say(f"{line}  {address}{tail}" if address else f"{line}{tail}")
    return 0


def main_use(app_name: str, *, hub: str = "") -> int:
    """Use an app, as **Use** does, and print the addresses it forwards.

    Args:
        app_name: The app as ``list`` names it.
        hub: What ``--hub`` named.

    Returns:
        0 once every forward listens, 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    app = names.choose_app(state, app_name, hub)
    if app is None:
        return 1
    body = {"hub_id": app.get("hub_id", ""), "app_id": app.get("id", "")}
    if wording.post("/api/app/use", body) is None:
        return 1
    fresh = wording.settled_state(_job_ended(app))
    if fresh is None:
        return 1
    row = _app_row(fresh, app) or {}
    failure = wording.refusal_of(row.get("last_error") or {})
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    for entry in names.app_entries(fresh, row or app):
        address = local_address(fresh, row or app, entry)
        if address:
            wording.say(wording.line("forwarding", address=address))
    return 0


def main_open(app_name: str, *, hub: str = "") -> int:
    """Open the browser at an app's first page, as **Open** does.

    Args:
        app_name: The app as ``list`` names it.
        hub: What ``--hub`` named.

    Returns:
        0 once the browser was told to open, 1 for a refusal:
        ``app_not_in_use`` for an app not in use, ``app_no_page`` for one
        with no web page.
    """
    state = wording.read_state()
    if state is None:
        return 1
    app = names.choose_app(state, app_name, hub)
    if app is None:
        return 1
    body = {"hub_id": app.get("hub_id", ""), "app_id": app.get("id", "")}
    if wording.post("/api/app/open", body) is None:
        return 1
    fresh = wording.settled_state(_job_ended(app))
    if fresh is None:
        return 1
    row = _app_row(fresh, app) or {}
    failure = wording.refusal_of(row.get("last_error") or {})
    if failure is not None:
        wording.refuse(failure["code"], failure["params"])
        return 1
    page = next(
        (
            entry
            for entry in names.app_entries(fresh, row or app)
            if entry.get("type") == "web"
        ),
        None,
    )
    if page is not None:
        address = local_address(fresh, row or app, page)
        wording.say(wording.line("opening", address=address))
    return 0


def main_stop(app_name: str, *, hub: str = "") -> int:
    """End an app's forwards, as **Stop** does.

    Args:
        app_name: The app as ``list`` names it.
        hub: What ``--hub`` named.

    Returns:
        0, or 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return 1
    app = names.choose_app(state, app_name, hub)
    if app is None:
        return 1
    body = {"hub_id": app.get("hub_id", ""), "app_id": app.get("id", "")}
    if wording.post("/api/app/stop", body) is None:
        return 1
    wording.settled_state(_job_ended(app))
    wording.say(wording.line("stopped", app=names.app_name(app)))
    return 0


def main_set(app_name: str, ports: list, *, hub: str = "") -> int:
    """Set entries' local ports on this client, as **Configure** does.

    Args:
        app_name: The app as ``list`` names it.
        ports: Each ``<entry>=<port>`` given, an empty port going back to
            the hub's.
        hub: What ``--hub`` named.

    Returns:
        0 when the numbers are kept, 1 for a refusal or a name that
        matches no entry, 2 for a ``--port`` of the wrong shape.
    """
    if not ports:
        wording.say(wording.line("port_missing"), is_error=True)
        return 2
    asked = {}
    for value in ports:
        name, separator, number = str(value).partition(APP_PORT_SEPARATOR)
        if not separator or not name or (number and not number.isdigit()):
            wording.say(wording.line("port_value_invalid", value=value), is_error=True)
            return 2
        asked[name] = int(number) if number else None
    state = wording.read_state()
    if state is None:
        return 1
    app = names.choose_app(state, app_name, hub)
    if app is None:
        return 1
    known = [str(entry.get("name", "")) for entry in names.app_entries(state, app)]
    for name in asked:
        if name not in known:
            wording.unknown_name("what_entry", name, known)
            return 1
    body = {
        "hub_id": app.get("hub_id", ""),
        "app_id": app.get("id", ""),
        "ports": asked,
    }
    reply = wording.post("/api/app/set", body)
    if reply is None:
        return 1
    row = _app_row(reply, app) or app
    for entry in names.app_entries(reply, row):
        if entry.get("name") in asked:
            address = local_address(reply, row, entry)
            wording.say(f"{entry.get('name', '')}  {address}".rstrip())
    return 0


def local_address(state: dict, app: dict, entry: dict) -> str:
    """One entry's fixed local address.

    Args:
        state: The state payload, for the platform.
        app: The app the entry belongs to.
        entry: The entry.

    Returns:
        ``<scheme>://<local name>:<port><path>`` for a ``web`` entry,
        ``<local name>:<port>`` for a ``port`` or ``ssh`` one, ``/udp``
        after a UDP one; the host is ``127.0.0.1`` on macOS. Empty while
        the entry has no number.
    """
    port = entry.get("local_port")
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        return ""
    host = str(app.get("local_name", "") or "")
    if (state.get("platform") or {}).get("os") == APP_LOOPBACK_OS or not host:
        host = APP_LOOPBACK_HOST
    payload = entry.get("payload") or {}
    if entry.get("type") == "web":
        parts = urllib.parse.urlsplit(str(payload.get("url", "")))
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return f"{parts.scheme or 'http'}://{host}:{port}{path}"
    suffix = "/udp" if payload.get("protocol") == "udp" else ""
    return f"{host}:{port}{suffix}"


def _is_unhealthy(entry: dict) -> bool:
    """Whether an entry's health is false; empty health is not unhealthy."""
    return entry.get("is_healthy") is False


def _app_row(state: dict, app: dict) -> "dict | None":
    """One app's row in a state, None when it is gone."""
    for row in names.apps(state, str(app.get("hub_id", ""))):
        if row.get("id") == app.get("id"):
            return row
    return None


def _job_ended(app: dict):
    """The check that one app's job has ended."""

    def is_ended(state: dict) -> bool:
        return not (_app_row(state, app) or {}).get("job")

    return is_ended
