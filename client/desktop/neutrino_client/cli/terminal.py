"""``nclient terminal``: shells and commands on the machines a hub manages.

A machine is one the hub offers a terminal on, named by its id or its name,
the hub named with ``--hub`` when several are joined; a session is named by
a unique prefix of its id. The running client opens the stream through its
hub, and this process carries its bytes over two control connections, one
each way. ``open`` and ``attach`` put this terminal in raw mode; ``exec``
does so only with ``--tty`` on a terminal, and otherwise carries stdin up
and the remote stdout and stderr down apart, so it works in a pipe.

Exit statuses: ``list`` 0, 1 when the client does not answer; ``open``,
``attach``, ``persist``, ``share`` and ``stop`` 0 done, 1 refused, 2 no
such machine or session; ``exec`` the remote command's code, 125 refused,
126 no such machine.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import threading

from neutrino_client.cli import wording
from neutrino_client.control import client
from neutrino_client.core.terminal import encode_piece, read_piece
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform

EXIT_CLOSED = 0
EXIT_REFUSED = 1
EXIT_NO_MACHINE = 2
EXIT_EXEC_REFUSED = 125
EXIT_EXEC_NO_MACHINE = 126
# The verbs ``nclient terminal`` takes; a bare machine is ``open``.
TERMINAL_VERBS = ("list", "open", "attach", "exec", "persist", "share", "stop")
TERMINAL_DEFAULT_VERB = "open"
# How much one read of the output, or of stdin, takes.
TERMINAL_READ_BYTES = 4096
# How much of a session id ``list`` shows.
TERMINAL_SESSION_ID_SHOWN = 8
# The ``fd`` byte of a frame the command wrote to stderr.
TERMINAL_FD_STDERR = 2
# The resident's routes a terminal is opened on.
TERMINAL_ATTACH_ROUTE = "/api/terminal/attach"
TERMINAL_EXEC_ROUTE = "/api/terminal/exec"
TERMINAL_OUTPUT_ROUTE = "/api/terminal/output"


def main_list(*, hub: str = "", is_json: bool = False) -> int:
    """Print every online machine and the sessions it keeps.

    Args:
        hub: The hub, by name or id; empty lists every hub joined.
        is_json: Print one JSON object instead of the table.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    machines = _machines(state, hub)
    if machines is None:
        return EXIT_REFUSED
    hub_names = {
        row.get("hub_id"): wording.hub_name(row) for row in state.get("hubs") or []
    }
    listed = [
        dict(
            machine,
            hub_name=hub_names.get(machine.get("hub_id"), ""),
            sessions=_sessions(state, machine),
        )
        for machine in machines
        if machine.get("is_online")
    ]
    if is_json:
        print(json.dumps({"machines": [_json_machine(row) for row in listed]}))
        return EXIT_CLOSED
    _print_table([wording.TERMINAL_LIST_COLUMNS] + _table_rows(listed))
    return EXIT_CLOSED


def main_open(
    machine: str,
    *,
    hub: str = "",
    is_persistent: bool = False,
    is_shared: bool = False,
    platform=None,
) -> int:
    """Open a new shell on one machine in this terminal.

    Args:
        machine: The machine's id or name.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.
        is_persistent: Whether the session is made persistent once the
            shell answers.
        is_shared: Whether the session is shared from its start.
        platform: The machine's platform; None detects it.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = _choose_machine(state, machine, hub, "is_shell_allowed")
    if chosen is None:
        return EXIT_NO_MACHINE
    return _run_shell(
        chosen,
        platform,
        session_id="",
        is_persistent=is_persistent,
        is_shared=is_shared,
    )


def main_attach(machine: str, session: str, *, hub: str = "", platform=None) -> int:
    """Attach this terminal to a shell session the machine keeps.

    Args:
        machine: The machine's id or name.
        session: The session's id, or a prefix of it that one session has.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.
        platform: The machine's platform; None detects it.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = _choose_machine(state, machine, hub, "is_shell_allowed")
    if chosen is None:
        return EXIT_NO_MACHINE
    row = _choose_session(state, chosen, session)
    if row is None:
        return EXIT_NO_MACHINE
    return _run_shell(chosen, platform, session_id=str(row["session_id"]))


def main_exec(
    machine: str,
    command: list,
    *,
    hub: str = "",
    is_tty: bool = False,
    platform=None,
    stdin=None,
    stdout=None,
    stderr=None,
) -> int:
    """Run one command on one machine and carry its input and outputs.

    Args:
        machine: The machine's id or name.
        command: The command and its arguments.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.
        is_tty: Whether the command runs on a pseudo-terminal; this terminal
            goes into raw mode for it when stdin is a terminal.
        platform: The machine's platform; None detects it.
        stdin: The binary stream the command's input is read from; None is
            this process's stdin.
        stdout: The binary stream the remote stdout goes to; None is this
            process's stdout.
        stderr: The binary stream the remote stderr goes to; None is this
            process's stderr.

    Returns:
        The remote command's exit code, or 125 or 126.
    """
    if not command:
        print(wording.EXEC_COMMAND_MISSING, file=sys.stderr)
        return EXIT_EXEC_REFUSED
    platform = platform if platform is not None else detect_platform()
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    stderr = stderr if stderr is not None else sys.stderr.buffer
    state = wording.read_state()
    if state is None:
        return EXIT_EXEC_REFUSED
    chosen = _choose_machine(state, machine, hub, "is_exec_allowed")
    if chosen is None:
        return EXIT_EXEC_NO_MACHINE
    try:
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_EXEC_REFUSED
    size = shutil.get_terminal_size()
    opened = _open_both(
        socket_path,
        TERMINAL_EXEC_ROUTE,
        {
            "hub_id": chosen["hub_id"],
            "device_id": chosen["device_id"],
            "argv": [str(part) for part in command],
            "is_tty": is_tty,
            "cols": size.columns,
            "rows": size.lines,
        },
    )
    if opened is None:
        return EXIT_EXEC_REFUSED
    terminal_id, keys, output = opened
    try:
        if is_tty and _is_terminal(stdin):
            with platform.raw_terminal() as term:
                term.on_resize(_resizer(terminal_id))
                is_carried = _carry_pieces(
                    term.read, term.write, _writer(stderr), keys, output, is_tty
                )
        else:
            is_carried = _carry_pieces(
                _reader(stdin), _writer(stdout), _writer(stderr), keys, output, is_tty
            )
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_EXEC_REFUSED
    except KeyboardInterrupt:
        return 128 + signal.SIGINT
    finally:
        keys.close()
        output.close()
    if not is_carried:
        return EXIT_EXEC_REFUSED
    outcome = _outcome(terminal_id)
    if outcome is None:
        return EXIT_EXEC_REFUSED
    exit_code = outcome.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return EXIT_EXEC_REFUSED
    return exit_code


def main_persist(machine: str, session: str, *, is_on: bool, hub: str = "") -> int:
    """Make one session stay after its last window closes, or stop staying.

    Args:
        machine: The machine's id or name.
        session: The session's id, or a prefix of it that one session has.
        is_on: Whether the session stays.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.

    Returns:
        The exit status.
    """
    return _session_verb(
        machine, session, hub, "/api/terminal/persist", {"is_persistent": is_on}
    )


def main_share(machine: str, session: str, *, is_on: bool, hub: str = "") -> int:
    """Share one session with every client with terminal rights, or stop.

    Args:
        machine: The machine's id or name.
        session: The session's id, or a prefix of it that one session has.
        is_on: Whether the session is shared.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.

    Returns:
        The exit status.
    """
    return _session_verb(
        machine, session, hub, "/api/terminal/persist", {"is_shared": is_on}
    )


def main_stop(machine: str, session: str, *, hub: str = "") -> int:
    """End one session the machine keeps.

    Args:
        machine: The machine's id or name.
        session: The session's id, or a prefix of it that one session has.
        hub: The hub, by name or id; empty names the one hub whose machines
            match.

    Returns:
        The exit status.
    """
    return _session_verb(machine, session, hub, "/api/terminal/stop", {})


def _machines(state: dict, hub: str) -> "list | None":
    """The machines of the hub named, or of every hub; None after a refusal."""
    machines = list((state.get("terminals") or {}).get("machines") or [])
    if not hub:
        return machines
    chosen_hub = wording.choose_hub(list(state.get("hubs") or []), hub)
    if chosen_hub is None:
        return None
    return [row for row in machines if row.get("hub_id") == chosen_hub["hub_id"]]


def _sessions(state: dict, machine: dict) -> list:
    """The sessions the state lists on one machine."""
    return [
        row
        for row in (state.get("terminals") or {}).get("sessions") or []
        if row.get("hub_id") == machine.get("hub_id")
        and row.get("device_id") == machine.get("device_id")
    ]


def _json_machine(machine: dict) -> dict:
    """One machine and its sessions as ``list --json`` prints them."""
    return {
        "hub_id": str(machine.get("hub_id", "")),
        "hub_name": str(machine.get("hub_name", "")),
        "device_id": str(machine.get("device_id", "")),
        "name": str(machine.get("name", "")),
        "is_shell_allowed": machine.get("is_shell_allowed") is True,
        "is_exec_allowed": machine.get("is_exec_allowed") is True,
        "sessions": [
            {
                "session_id": str(row.get("session_id", "")),
                "title": str(row.get("title", "")),
                "account": str(row.get("account", "")),
                "owner": str(row.get("owner", "")),
                "owner_name": str(row.get("owner_name", "")),
                "is_owned": row.get("is_owned") is True,
                "is_persistent": row.get("is_persistent") is True,
                "is_shared": row.get("is_shared") is True,
                "attached_count": int(row.get("attached_count") or 0),
            }
            for row in machine["sessions"]
        ],
    }


def _table_rows(machines: list) -> list:
    """One row per session, and one for a machine that keeps none."""
    rows = []
    for machine in machines:
        head = [str(machine.get("name", "")), str(machine.get("hub_name", ""))]
        if not machine["sessions"]:
            empty = len(wording.TERMINAL_LIST_COLUMNS) - len(head)
            rows.append(head + [wording.TERMINAL_LIST_NONE] * empty)
            continue
        for row in machine["sessions"]:
            rows.append(
                head
                + [
                    str(row.get("session_id", ""))[:TERMINAL_SESSION_ID_SHOWN],
                    str(row.get("title", "")) or wording.TERMINAL_LIST_NONE,
                    str(row.get("account", "")) or wording.TERMINAL_LIST_NONE,
                    str(row.get("owner_name", "") or row.get("owner", ""))
                    or wording.TERMINAL_LIST_NONE,
                    _yes_no(row.get("is_owned")),
                    _yes_no(row.get("is_persistent")),
                    _yes_no(row.get("is_shared")),
                    str(int(row.get("attached_count") or 0)),
                ]
            )
    return rows


def _yes_no(value) -> str:
    return wording.TERMINAL_LIST_YES if value is True else wording.TERMINAL_LIST_NO


def _print_table(rows: list) -> None:
    """Print rows in columns two spaces apart."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


def _choose_machine(state: dict, needle: str, hub: str, kind: str) -> "dict | None":
    """The one named machine that offers ``kind``, or None after saying why."""
    machines = _machines(state, hub)
    if machines is None:
        return None
    matches = [
        row
        for row in machines
        if needle in (row.get("device_id"), row.get("name")) and row.get(kind) is True
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


def _choose_session(state: dict, machine: dict, prefix: str) -> "dict | None":
    """The one session whose id starts with ``prefix``, or None after saying why."""
    matches = [
        row
        for row in _sessions(state, machine)
        if prefix and str(row.get("session_id", "")).startswith(prefix)
    ]
    if not matches:
        print(
            wording.word_code("session_unknown", {"session_id": prefix}),
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        print(
            wording.SESSION_AMBIGUOUS_LINE.format(
                prefix=prefix, machine=machine.get("name", "")
            ),
            file=sys.stderr,
        )
        for row in matches:
            print(
                f"  {row.get('session_id', '')}  {row.get('title', '')}".rstrip(),
                file=sys.stderr,
            )
        return None
    return matches[0]


def _session_verb(machine: str, session: str, hub: str, path: str, flags: dict) -> int:
    """Send one session verb to the resident and say how it went."""
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = _choose_machine(state, machine, hub, "is_shell_allowed")
    if chosen is None:
        return EXIT_NO_MACHINE
    row = _choose_session(state, chosen, session)
    if row is None:
        return EXIT_NO_MACHINE
    answer = wording.request(
        "POST",
        path,
        dict(flags, hub_id=chosen["hub_id"], session_id=str(row["session_id"])),
    )
    if answer is None:
        return EXIT_REFUSED
    status, reply = answer
    if status == 200:
        return EXIT_CLOSED
    code = str(reply.get("code", "") or "")
    print(wording.word_code(code, reply.get("params")), file=sys.stderr)
    return EXIT_NO_MACHINE if code == "session_unknown" else EXIT_REFUSED


def _run_shell(
    chosen: dict,
    platform,
    *,
    session_id: str,
    is_persistent: bool = False,
    is_shared: bool = False,
) -> int:
    """Open or attach a shell on the chosen machine and carry it in raw mode."""
    platform = platform if platform is not None else detect_platform()
    try:
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_REFUSED
    size = shutil.get_terminal_size()
    body = {
        "hub_id": chosen["hub_id"],
        "device_id": chosen["device_id"],
        "cols": size.columns,
        "rows": size.lines,
        "session_id": session_id,
    }
    if is_shared:
        body["is_shared"] = True
    opened = _open_both(socket_path, TERMINAL_ATTACH_ROUTE, body)
    if opened is None:
        return EXIT_REFUSED
    terminal_id, keys, output = opened
    try:
        with platform.raw_terminal() as term:
            _carry(term, keys, output, terminal_id, is_persistent)
    except PlatformUnsupportedError as error:
        print(wording.word_code(error.code), file=sys.stderr)
        return EXIT_REFUSED
    finally:
        keys.close()
        output.close()
    outcome = _outcome(terminal_id)
    if outcome is None or outcome.get("code"):
        return EXIT_REFUSED
    return EXIT_CLOSED


def _open_both(socket_path: str, path: str, body: dict) -> "tuple | None":
    """The terminal's id and its two connections, or None after the refusal."""
    typing = _upgrade(socket_path, path, body)
    if typing is None:
        return None
    terminal_id, keys = typing
    shown = _upgrade(socket_path, TERMINAL_OUTPUT_ROUTE, {"terminal_id": terminal_id})
    if shown is None:
        keys.close()
        return None
    return terminal_id, keys, shown[1]


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


def _resizer(terminal_id: str):
    """The callback that sends one terminal's new size up as a request."""

    def resized(cols: int, rows: int) -> None:
        wording.request(
            "POST",
            "/api/terminal/resize",
            {"terminal_id": terminal_id, "cols": cols, "rows": rows},
        )

    return resized


def _carry(term, keys, output, terminal_id: str, is_persistent: bool) -> None:
    """Keys up on a thread, output down here; persistent after the first output."""

    def send_keys() -> None:
        while True:
            data = term.read()
            if not data:
                break
            try:
                keys.send(data)
            except OSError:
                break

    term.on_resize(_resizer(terminal_id))
    threading.Thread(target=send_keys, name="terminal_keys", daemon=True).start()
    while True:
        data = output.read(TERMINAL_READ_BYTES)
        if not data:
            return
        term.write(data)
        if is_persistent:
            is_persistent = False
            threading.Thread(
                target=_persist_open,
                args=(terminal_id,),
                name="terminal_persist",
                daemon=True,
            ).start()


def _persist_open(terminal_id: str) -> None:
    """Make an open terminal's session persistent; a refusal is printed."""
    answer = wording.request(
        "POST",
        "/api/terminal/persist",
        {"terminal_id": terminal_id, "is_persistent": True},
    )
    if answer is not None and answer[0] != 200:
        print(
            wording.word_code(str(answer[1].get("code", "")), answer[1].get("params")),
            end="\r\n",
            file=sys.stderr,
        )


def _carry_pieces(read_input, write_out, write_err, keys, output, is_tty: bool) -> bool:
    """Input up on a thread, output down here; False when an output failed."""

    def send_input() -> None:
        while True:
            data = read_input()
            if not data:
                break
            try:
                keys.send(encode_piece(data))
            except OSError:
                return
        if not is_tty:
            try:
                keys.send(encode_piece(b""))
            except OSError:
                return

    threading.Thread(target=send_input, name="exec_input", daemon=True).start()
    while True:
        piece = read_piece(output.read)
        if piece is None:
            return True
        if not piece:
            continue
        write = write_err if piece[0] == TERMINAL_FD_STDERR else write_out
        try:
            write(piece[1:])
        except OSError:
            return False


def _reader(stream):
    """``read()`` over a binary stream: what is there now, empty at its end.

    A stream with a file descriptor is read through it, so the thread that
    waits on stdin holds no buffer lock while the process exits.
    """

    def read() -> bytes:
        try:
            try:
                descriptor = stream.fileno()
            except (OSError, ValueError, AttributeError):
                descriptor = None
            if descriptor is not None:
                return os.read(descriptor, TERMINAL_READ_BYTES)
            if hasattr(stream, "read1"):
                return stream.read1(TERMINAL_READ_BYTES)
            return stream.read(TERMINAL_READ_BYTES)
        except (OSError, ValueError):
            return b""

    return read


def _writer(stream):
    """``write(data)`` over a binary stream, flushed at once."""

    def write(data: bytes) -> None:
        stream.write(data)
        stream.flush()

    return write


def _is_terminal(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _outcome(terminal_id: str) -> "dict | None":
    """How the stream ended, a refusal printed; None when the client did not answer."""
    answer = wording.request(
        "POST", "/api/terminal/result", {"terminal_id": terminal_id}
    )
    if answer is None:
        return None
    _status, outcome = answer
    code = str(outcome.get("code", "") or "")
    if code:
        print(wording.word_code(code, outcome.get("params")), file=sys.stderr)
    return outcome
