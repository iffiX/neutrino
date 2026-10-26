"""``nclient terminal``: shells and commands on the machines a hub manages.

A machine is one the hub offers a terminal on, named by its name or its id,
the hub named with ``--hub`` when two hold a machine of one name; a session
is named by a prefix of its id, as git names a commit. The running client
opens the stream through its hub as the account named, the machine's first
enabled one by default, and this process carries its bytes over two
control connections, one each way. ``open`` and ``attach`` put this
terminal in raw mode; ``exec`` does so only with ``--tty`` on a terminal,
and otherwise carries stdin up and the remote stdout and stderr down apart,
so it works in a pipe.

Exit statuses: ``list`` 0, 1 when the client does not answer; ``open``,
``attach``, ``set`` and ``stop`` 0 done, 1 refused, 2 no such machine or
session; ``exec`` the remote command's code, 125 refused, 126 no such
machine.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import signal
import sys
import threading
import time

from neutrino_client.cli import names, wording
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
TERMINAL_VERBS = ("list", "open", "attach", "exec", "set", "stop")
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
# How long a session has been open is said in the largest of these units.
TERMINAL_AGE_UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))


def main_list(machine: str, *, hub: str = "") -> int:
    """Print one machine's sessions.

    Each line is the id's first characters, the account, how long it has
    been open, whether it is persistent, whether it is shared, and how many
    windows are attached.

    Args:
        machine: The machine's name or id.
        hub: What ``--hub`` named.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = names.choose_terminal_machine(state, machine, hub)
    if chosen is None:
        return EXIT_NO_MACHINE
    sessions = names.session_rows(state, chosen)
    if not sessions:
        wording.say(wording.line("terminal_none", machine=chosen.get("name", "")))
        return EXIT_CLOSED
    header = [
        wording.line(key)
        for key in (
            "terminal_session",
            "terminal_account",
            "terminal_open_for",
            "terminal_persistent",
            "terminal_shared",
            "terminal_attached",
        )
    ]
    rows = [header] + [_session_cells(row) for row in sessions]
    _print_table(rows)
    return EXIT_CLOSED


def main_open(machine: str, *, account: str = "", hub: str = "", platform=None) -> int:
    """Open a new shell on one machine in this terminal.

    Args:
        machine: The machine's name or id.
        account: The enabled account to run as; empty is the first.
        hub: What ``--hub`` named.
        platform: The machine's platform; None detects it.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = names.choose_terminal_machine(state, machine, hub)
    if chosen is None:
        return EXIT_NO_MACHINE
    return _run_shell(chosen, platform, session_id="", account=account)


def main_attach(machine: str, session: str, *, hub: str = "", platform=None) -> int:
    """Attach this terminal to a shell session the machine keeps.

    Args:
        machine: The machine's name or id.
        session: The session's id, or a prefix of it that one session has.
        hub: What ``--hub`` named.
        platform: The machine's platform; None detects it.

    Returns:
        The exit status.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = names.choose_terminal_machine(state, machine, hub)
    if chosen is None:
        return EXIT_NO_MACHINE
    row = names.choose_session(state, chosen, session)
    if row is None:
        return EXIT_NO_MACHINE
    return _run_shell(chosen, platform, session_id=str(row["session_id"]))


def main_exec(
    machine: str,
    command: list,
    *,
    account: str = "",
    hub: str = "",
    is_tty: bool = False,
    platform=None,
    stdin=None,
    stdout=None,
    stderr=None,
) -> int:
    """Run one command on one machine and carry its input and outputs.

    Args:
        machine: The machine's name or id.
        command: The command and its arguments.
        account: The enabled account to run as; empty is the first.
        hub: What ``--hub`` named.
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
        wording.say(wording.line("exec_command_missing"), is_error=True)
        return EXIT_EXEC_REFUSED
    platform = platform if platform is not None else detect_platform()
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    stderr = stderr if stderr is not None else sys.stderr.buffer
    state = wording.read_state()
    if state is None:
        return EXIT_EXEC_REFUSED
    chosen = names.choose_terminal_machine(state, machine, hub)
    if chosen is None:
        return EXIT_EXEC_NO_MACHINE
    try:
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        wording.refuse(error.code)
        return EXIT_EXEC_REFUSED
    size = shutil.get_terminal_size()
    opened = open_both(
        socket_path,
        TERMINAL_EXEC_ROUTE,
        {
            "hub_id": chosen["hub_id"],
            "device_id": chosen["device_id"],
            "argv": [str(part) for part in command],
            "is_tty": is_tty,
            "cols": size.columns,
            "rows": size.lines,
            "account": account,
        },
        machine=chosen,
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
        wording.refuse(error.code)
        return EXIT_EXEC_REFUSED
    except KeyboardInterrupt:
        return 128 + signal.SIGINT
    finally:
        keys.close()
        output.close()
    if not is_carried:
        return EXIT_EXEC_REFUSED
    outcome = outcome_of(terminal_id, machine=chosen)
    if outcome is None:
        return EXIT_EXEC_REFUSED
    exit_code = outcome.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return EXIT_EXEC_REFUSED
    return exit_code


def main_set(
    machine: str,
    session: str,
    *,
    is_persistent: "bool | None" = None,
    is_shared: "bool | None" = None,
    hub: str = "",
) -> int:
    """Change whether a session stays after its last window, and who sees it.

    Only the session's owner changes it; any other client is refused
    ``session_not_owned``.

    Args:
        machine: The machine's name or id.
        session: The session's id, or a prefix of it that one session has.
        is_persistent: Whether the session stays; None leaves it.
        is_shared: Whether other clients can attach; None leaves it.
        hub: What ``--hub`` named.

    Returns:
        The exit status.
    """
    flags = {}
    if is_persistent is not None:
        flags["is_persistent"] = is_persistent
    if is_shared is not None:
        flags["is_shared"] = is_shared
    if not flags:
        wording.say(wording.line("session_flags_missing"), is_error=True)
        return EXIT_NO_MACHINE
    return _session_verb(machine, session, hub, "/api/terminal/persist", flags)


def main_stop(machine: str, session: str, *, hub: str = "") -> int:
    """End one session the machine keeps, and every program in it.

    Args:
        machine: The machine's name or id.
        session: The session's id, or a prefix of it that one session has.
        hub: What ``--hub`` named.

    Returns:
        The exit status.
    """
    return _session_verb(machine, session, hub, "/api/terminal/stop", {})


def open_both(
    socket_path: str, path: str, body: dict, *, machine: "dict | None" = None
) -> "tuple | None":
    """A kept stream's id and its two connections, one each way.

    Args:
        socket_path: The control socket.
        path: The route that opens the stream and answers 101.
        body: What it is sent.
        machine: The machine the stream reaches, to name it in a refusal.

    Returns:
        ``(terminal_id, keys, output)``: the connection that carries this
        side's bytes up and the one that carries the stream's bytes down;
        None after the refusal was printed.
    """
    typing = _upgrade(socket_path, path, body, machine)
    if typing is None:
        return None
    terminal_id, keys = typing
    shown = _upgrade(
        socket_path, TERMINAL_OUTPUT_ROUTE, {"terminal_id": terminal_id}, machine
    )
    if shown is None:
        keys.close()
        return None
    return terminal_id, keys, shown[1]


def outcome_of(terminal_id: str, *, machine: "dict | None" = None) -> "dict | None":
    """How a kept stream ended, a refusal printed.

    Args:
        terminal_id: The stream's id.
        machine: The machine it reached, to name it in a refusal.

    Returns:
        ``{"exit_code"}`` or the refusal; None when the client did not answer.
    """
    answer = wording.request(
        "POST", "/api/terminal/result", {"terminal_id": terminal_id}
    )
    if answer is None:
        return None
    _status, outcome = answer
    code = str(outcome.get("code", "") or "")
    if code:
        wording.refuse(code, machine_params(outcome.get("params"), machine))
    return outcome


def machine_params(params, machine: "dict | None") -> dict:
    """A refusal's params with its machine named as the person names it.

    Args:
        params: The refusal's params.
        machine: The machine the request reached, or None.

    Returns:
        The params, ``device`` the machine's name where it names its id.
    """
    values = dict(params) if isinstance(params, dict) else {}
    if machine and values.get("device") in (machine.get("device_id"), None, ""):
        values["device"] = machine.get("name") or values.get("device", "")
    return values


def _session_cells(row: dict) -> list:
    """One session's cells in ``list``."""
    return [
        str(row.get("session_id", ""))[:TERMINAL_SESSION_ID_SHOWN],
        str(row.get("account", "")) or wording.line("none"),
        _age(row.get("started_at")),
        _yes_no(row.get("is_persistent")),
        _yes_no(row.get("is_shared")),
        str(int(row.get("attached_count") or 0)),
    ]


def _age(started_at) -> str:
    """How long ago a session started, in its largest unit."""
    if isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
        return wording.line("none")
    seconds = max(int(time.time() - started_at), 0)
    for unit, size in TERMINAL_AGE_UNITS:
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return "0s"


def _yes_no(value) -> str:
    return wording.line("yes") if value is True else wording.line("no")


def _print_table(rows: list) -> None:
    """Print rows in columns two spaces apart."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        wording.say(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
        )


def _session_verb(machine: str, session: str, hub: str, path: str, flags: dict) -> int:
    """Send one session verb to the client and say how it went."""
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    chosen = names.choose_terminal_machine(state, machine, hub)
    if chosen is None:
        return EXIT_NO_MACHINE
    row = names.choose_session(state, chosen, session)
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
    if status == 200 and not reply.get("code"):
        return EXIT_CLOSED
    code = str(reply.get("code", "") or "")
    wording.refuse(code, machine_params(reply.get("params"), chosen))
    return EXIT_NO_MACHINE if code == "session_unknown" else EXIT_REFUSED


def _run_shell(chosen: dict, platform, *, session_id: str, account: str = "") -> int:
    """Open or attach a shell on the chosen machine and carry it in raw mode."""
    platform = platform if platform is not None else detect_platform()
    try:
        socket_path = platform.control_socket_path()
    except PlatformUnsupportedError as error:
        wording.refuse(error.code)
        return EXIT_REFUSED
    size = shutil.get_terminal_size()
    body = {
        "hub_id": chosen["hub_id"],
        "device_id": chosen["device_id"],
        "cols": size.columns,
        "rows": size.lines,
        "session_id": session_id,
        "account": account,
    }
    opened = open_both(socket_path, TERMINAL_ATTACH_ROUTE, body, machine=chosen)
    if opened is None:
        return EXIT_REFUSED
    terminal_id, keys, output = opened
    try:
        with platform.raw_terminal() as term:
            _carry(term, keys, output, terminal_id)
    except PlatformUnsupportedError as error:
        wording.refuse(error.code)
        return EXIT_REFUSED
    finally:
        keys.close()
        output.close()
    outcome = outcome_of(terminal_id, machine=chosen)
    if outcome is None or outcome.get("code"):
        return EXIT_REFUSED
    return EXIT_CLOSED


def _upgrade(
    socket_path: str, path: str, body: dict, machine: "dict | None"
) -> "tuple | None":
    """One kept connection, or None after the refusal was printed."""
    try:
        status, reply, connection = client.upgrade(
            socket_path=socket_path, path=path, body=body
        )
    except (OSError, ValueError):
        wording.refuse("client_not_running")
        return None
    if status != 101 or connection is None:
        wording.refuse(
            str(reply.get("code", "")), machine_params(reply.get("params"), machine)
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


def _carry(term, keys, output, terminal_id: str) -> None:
    """Keys up on a thread, output down here."""

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
