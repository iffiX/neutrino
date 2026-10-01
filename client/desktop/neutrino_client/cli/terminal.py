"""``nclient terminal <machine>``: a shell on a machine a hub manages.

The machine is one the hub offers a terminal on, named by its id or its
name, the hub named with ``--hub`` when several are joined; ``--session``
attaches to a shell session the machine keeps, by its id. The running
client opens the shell through its hub; this terminal is put in raw mode
and carries every key there and the shell's output back, over two control
connections, one each way. A size change goes up as a resize.

Exit statuses: 0 once the hub closed the shell, 1 for a refusal, 2 for a
machine that is not offered.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import shutil
import sys
import threading

from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

EXIT_CLOSED = 0
EXIT_REFUSED = 1
EXIT_NO_MACHINE = 2
# How much one read of the shell's output takes.
TERMINAL_READ_BYTES = 4096


def main(machine: str, *, hub: str = "", session_id: str = "", platform=None) -> int:
    """Attach this terminal to a shell on one machine.

    Args:
        machine: The machine's id or name.
        hub: The hub, by name or id; empty names the one hub whose
            machines match.
        session_id: A shell session the machine keeps, attached to again;
            empty opens a new one.
        platform: The machine's platform; None detects it.

    Returns:
        The exit status.
    """
    platform = platform if platform is not None else detect_platform()
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = _choose_machine(state, machine, hub)
    if chosen is None:
        return EXIT_NO_MACHINE
    try:
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_REFUSED
    size = shutil.get_terminal_size()
    typing = _upgrade(
        socket_path,
        "/api/terminal/attach",
        {
            "hub_id": chosen["hub_id"],
            "device_id": chosen["device_id"],
            "cols": size.columns,
            "rows": size.lines,
            "session_id": session_id,
        },
    )
    if typing is None:
        return EXIT_REFUSED
    terminal_id, keys = typing
    shown = _upgrade(socket_path, "/api/terminal/output", {"terminal_id": terminal_id})
    if shown is None:
        keys.close()
        return EXIT_REFUSED
    output = shown[1]
    try:
        with platform.raw_terminal() as term:
            _carry(term, keys, output, terminal_id)
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_REFUSED
    finally:
        keys.close()
        output.close()
    return _ended(terminal_id)


def _choose_machine(state: dict, needle: str, hub: str) -> "dict | None":
    """The one offered machine the person named, or None after saying why."""
    terminals = state.get("terminals")
    machines = list((terminals or {}).get("machines") or [])
    if hub:
        chosen_hub = wording.choose_hub(list(state.get("hubs") or []), hub)
        if chosen_hub is None:
            return None
        machines = [
            row for row in machines if row.get("hub_id") == chosen_hub["hub_id"]
        ]
    matches = [
        row for row in machines if needle in (row.get("device_id"), row.get("name"))
    ]
    if not matches:
        print(
            wording.word_code("unknown_terminal", {"device_id": needle}),
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        names = ", ".join(
            wording.hub_name(row)
            for row in state.get("hubs") or []
            if row.get("hub_id") in {match["hub_id"] for match in matches}
        )
        print(wording.word_code("ambiguous_hub", {"hubs": names}), file=sys.stderr)
        return None
    return matches[0]


def _upgrade(socket_path: str, path: str, body: dict) -> "tuple | None":
    """One kept connection, or None after the refusal was printed."""
    try:
        status, reply, connection = client.upgrade(
            socket_path=socket_path, path=path, body=body
        )
    except (OSError, ValueError):
        print(wording.word_code("resident_not_running"), file=sys.stderr)
        return None
    if status != 101 or connection is None:
        print(
            wording.word_code(str(reply.get("code", "")), reply.get("params")),
            file=sys.stderr,
        )
        return None
    return str(reply.get("terminal_id", "")), connection


def _carry(term, keys, output, terminal_id: str) -> None:
    """Keys up on a thread of their own, output down here, until the shell ends."""

    def resized(cols: int, rows: int) -> None:
        wording.request(
            "POST",
            "/api/terminal/resize",
            {"terminal_id": terminal_id, "cols": cols, "rows": rows},
        )

    def send_keys() -> None:
        while True:
            data = term.read()
            if not data:
                break
            try:
                keys.send(data)
            except OSError:
                break

    term.on_resize(resized)
    threading.Thread(target=send_keys, name="terminal_keys", daemon=True).start()
    while True:
        data = output.read(TERMINAL_READ_BYTES)
        if not data:
            return
        term.write(data)


def _ended(terminal_id: str) -> int:
    """Ask how the shell ended; a refusal is printed."""
    answer = wording.request(
        "POST", "/api/terminal/result", {"terminal_id": terminal_id}
    )
    if answer is None:
        return EXIT_REFUSED
    _status, outcome = answer
    code = str(outcome.get("code", "") or "")
    if code:
        print(wording.word_code(code, outcome.get("params")), file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_CLOSED
