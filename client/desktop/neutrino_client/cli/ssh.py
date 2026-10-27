"""``nclient ssh``: the machines' SSH servers, for ssh and every program that speaks it.

The running client writes ``~/.ssh/neutrino_config``: one ``Host
<machine>.nt`` per machine with an ``ssh`` entry, its ``ProxyCommand`` this
command's ``proxy``. ``list`` prints the machines and their accounts, the
default first, each account with its entry's fixed local address
``127.0.0.1:<local port>``, where the running client forwards it for a
program that takes only a host and a port; ``open`` runs the system's
``ssh`` against that file; ``config`` shows it and adds or takes out the
``Include`` line in ``~/.ssh/config``, as the Settings switch does;
``proxy`` joins its standard input and output to the account's SSH server
through the client.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from neutrino_client.cli import names, terminal, wording
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform
from neutrino_client.services.forward import FORWARD_BIND_HOST

SSH_PROGRAM = "ssh"
SSH_PROXY_ROUTE = "/api/ssh/proxy"
# How much one read of stdin, or of the stream, takes.
SSH_PROXY_READ_BYTES = 65536
# The line a change of the Include line reads, by whether it went in.
SSH_INCLUDE_LINES = {True: "ssh_installed", False: "ssh_uninstalled"}
EXIT_CLOSED = 0
EXIT_REFUSED = 1


def main_list(*, hub: str = "") -> int:
    """Print each machine with an ``ssh`` entry and its accounts, the default first.

    Each account is followed by its entry's local address, left out while
    the entry has no number.

    Args:
        hub: What ``--hub`` named; empty lists every hub's.

    Returns:
        0, or 1 when the client does not answer or ``--hub`` names nothing.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    is_known, hub_id = names.scope(state, hub)
    if not is_known:
        return EXIT_REFUSED
    machines = [
        row for row in names.ssh_hosts(state) if not hub_id or row["hub_id"] == hub_id
    ]
    width = max((len(row["host"]) for row in machines), default=0)
    for row in machines:
        accounts = "  ".join(
            _account_address(account, entry)
            for account, entry in zip(row["accounts"], row["entries"])
        )
        wording.say(f"{row['host']:<{width}}  {accounts}")
    return EXIT_CLOSED


def main_open(target: str, command: list, *, hub: str = "", run=None) -> int:
    """Run the system's ``ssh`` against one machine, through the client's file.

    Args:
        target: ``[<account>@]<machine>``.
        command: The command after ``--``; empty logs in.
        hub: What ``--hub`` named.
        run: ``run(argv) -> int`` runs the program; None runs it here.

    Returns:
        ``ssh``'s own exit status, or 1 for a refusal.
    """
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    found = names.choose_ssh(state, target, hub)
    if found is None:
        return EXIT_REFUSED
    machine, entry = found
    config = _config()
    if config is None:
        return EXIT_REFUSED
    account = str((entry.get("payload") or {}).get("account", "") or "")
    argv = [
        _ssh_program(),
        "-F",
        str(config.get("path", "")),
        f"{account}@{machine['host']}{names.SSH_HOST_SUFFIX}",
    ]
    argv += [str(part) for part in command]
    runner = run if run is not None else subprocess.call
    try:
        return runner(argv)
    except OSError as error:
        wording.refuse("bundle_missing", {"binary": f"{SSH_PROGRAM} ({error})"})
        return EXIT_REFUSED


def main_config_show() -> int:
    """Print the path and the text of ``~/.ssh/neutrino_config``.

    Returns:
        0, or 1 when the client does not answer.
    """
    config = _config()
    if config is None:
        return EXIT_REFUSED
    path = str(config.get("path", ""))
    text = str(config.get("text", "") or "")
    wording.say(path)
    if not text:
        wording.say(wording.line("ssh_config_absent", path=path))
        return EXIT_CLOSED
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return EXIT_CLOSED


def main_config_install(*, is_installed: bool) -> int:
    """Add or take out the ``Include`` line, as the Settings switch does.

    Args:
        is_installed: Whether the line goes in.

    Returns:
        0, or 1 for a refusal.
    """
    body = {"is_ssh_include_enabled": is_installed}
    if wording.post("/api/settings/set", body) is None:
        return EXIT_REFUSED
    wording.say(wording.line(SSH_INCLUDE_LINES[is_installed]))
    return EXIT_CLOSED


def main_proxy(target: str, *, hub: str = "", stdin=None, stdout=None) -> int:
    """Join standard input and output to an account's SSH server, for ProxyCommand.

    Nothing but the stream's bytes goes to stdout; a refusal is one line on
    stderr.

    Args:
        target: ``[<account>@]<machine>[.nt]``, as ssh gives ``%r@%h``.
        hub: What ``--hub`` named.
        stdin: The binary stream read up; None is this process's stdin.
        stdout: The binary stream written down; None is this process's
            stdout.

    Returns:
        0 when the stream ends, 1 for a refusal.
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    state = wording.read_state()
    if state is None:
        return EXIT_REFUSED
    found = names.choose_ssh(state, target, hub)
    if found is None:
        return EXIT_REFUSED
    machine, entry = found
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError as error:
        wording.refuse(error.code)
        return EXIT_REFUSED
    named = {"device_id": machine["device_id"], "name": machine["name"]}
    opened = terminal.open_both(
        socket_path,
        SSH_PROXY_ROUTE,
        {"hub_id": entry.get("hub_id", ""), "entry_id": entry.get("id", "")},
        machine=named,
    )
    if opened is None:
        return EXIT_REFUSED
    terminal_id, up, down = opened
    try:
        _relay(stdin, stdout, up, down)
    finally:
        up.close()
        down.close()
    outcome = terminal.outcome_of(terminal_id, machine=named)
    if outcome is None or outcome.get("code"):
        return EXIT_REFUSED
    return EXIT_CLOSED


def _account_address(account: str, entry: dict) -> str:
    """One account and its entry's local address, as ``list`` prints them."""
    port = entry.get("local_port")
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        return account
    return f"{account} {FORWARD_BIND_HOST}:{port}"


def _relay(stdin, stdout, up, down) -> None:
    """Stdin up on a thread, the stream's bytes down here until it ends."""

    def send_up() -> None:
        while True:
            try:
                data = _read_some(stdin)
            except (OSError, ValueError):
                data = b""
            if not data:
                break
            try:
                up.send(data)
            except OSError:
                return
        try:
            up.close()
        except OSError:
            pass

    threading.Thread(target=send_up, name="ssh_proxy_up", daemon=True).start()
    while True:
        data = down.read(SSH_PROXY_READ_BYTES)
        if not data:
            return
        try:
            stdout.write(data)
            stdout.flush()
        except OSError:
            return


def _read_some(stream) -> bytes:
    """What a binary stream holds now, empty at its end."""
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError, AttributeError):
        descriptor = None
    if descriptor is not None:
        return os.read(descriptor, SSH_PROXY_READ_BYTES)
    if hasattr(stream, "read1"):
        return stream.read1(SSH_PROXY_READ_BYTES)
    return stream.read(SSH_PROXY_READ_BYTES)


def _config() -> "dict | None":
    """``{path, text}`` of the client's SSH configuration, or None after a refusal."""
    answer = wording.request("GET", "/api/ssh/config")
    if answer is None:
        return None
    _status, reply = answer
    refusal = wording.refusal_of(reply)
    if refusal is not None:
        wording.refuse(refusal["code"], refusal["params"])
        return None
    return reply


def _ssh_program() -> str:
    """The system's ``ssh``, by its full path where the search path finds it."""
    return shutil.which(SSH_PROGRAM) or SSH_PROGRAM
