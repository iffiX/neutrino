"""Running a program on a terminal of its own and answering one question.

A tool that asks ``(y/N)`` on its terminal and takes no flag in the
answer's place, as cc-switch's ``provider delete`` does, is given a
terminal: a pseudo-terminal on Linux and macOS, a pseudo console on Windows.
What it prints is read until the question shows, the answer is typed, and
the rest is read until the program ends.

Not pure: starts processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import subprocess
import time

from neutrino_agent.constants import (
    AGENT_ANSWER_EXIT_TIMEOUT_S,
    AGENT_ANSWER_PROMPT_TIMEOUT_S,
    AGENT_ANSWER_READ_BYTES,
)
from neutrino_agent.exceptions import PlatformUnsupportedError

try:
    import select
except ImportError:  # Every system has it; kept guarded like the POSIX ones.
    select = None

# What a terminal weaves through its text: cursor moves and colours (CSI),
# titles (OSC, ended by a bell or a string terminator), and the two-byte
# escapes.
TERMINAL_SEQUENCES = re.compile(
    rb"\x1b\[[0-9;?]*[ -/]*[@-~]"
    rb"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\\\)?"
    rb"|\x1b[@-Z\\\\-_]"
)
# The exit status of a program that could not be started.
NOT_STARTED_EXIT = 127


def plain_text(output: bytes) -> bytes:
    """A terminal's output with its control sequences taken out.

    Args:
        output: What the terminal printed.

    Returns:
        The text alone.
    """
    return TERMINAL_SEQUENCES.sub(b"", output)


def answer_on_prompt(
    read,
    write,
    *,
    prompt: str,
    answer: str,
    deadline: float,
    prompt_deadline: "float | None" = None,
) -> bytes:
    """Read a terminal until it ends, answering the prompt once it shows.

    Args:
        read: ``read(wait_s)`` -> bytes; empty at the end, None when nothing
            arrived in time.
        write: ``write(data)`` sends bytes to the terminal.
        prompt: The text the answer follows.
        answer: What to send once the prompt has shown.
        deadline: A ``time.monotonic()`` value past which reading stops.
        prompt_deadline: A ``time.monotonic()`` value past which reading
            stops while the prompt has not shown; None reads to the
            deadline.

    Returns:
        Everything the terminal printed.
    """
    output = b""
    marker = prompt.encode("utf-8")
    is_answered = False
    while time.monotonic() < deadline:
        if (
            not is_answered
            and prompt_deadline is not None
            and time.monotonic() >= prompt_deadline
        ):
            break
        chunk = read(0.5)
        if chunk is None:
            continue
        if not chunk:
            break
        output += chunk
        if not is_answered and marker in plain_text(output):
            write(answer.encode("utf-8"))
            is_answered = True
    return output


def run_on_pty(
    argv: list,
    *,
    prompt: str,
    answer: str,
    timeout_s: float,
    env: "dict | None" = None,
    cwd: "str | None" = None,
    user: "int | None" = None,
    group: "int | None" = None,
) -> tuple:
    """Run a program on a pseudo-terminal and answer one prompt.

    Args:
        argv: Argument vector.
        prompt: The text the answer follows.
        answer: The keystrokes to send, newline included.
        timeout_s: How long the whole run may take.
        env: The program's whole environment; None passes the agent's.
        cwd: Where it starts; None is the agent's own directory.
        user: The uid it runs as; None keeps the agent's.
        group: The gid it runs as, with no supplementary groups; None
            keeps the agent's.

    Returns:
        ``(returncode, output)``; 127 when the program could not start.

    Raises:
        PlatformUnsupportedError: Where this interpreter has no
            pseudo-terminal.
    """
    if not hasattr(os, "openpty") or select is None:
        raise PlatformUnsupportedError("no pseudo-terminal on this platform")
    leader, follower = os.openpty()
    extra = {}
    if user is not None:
        extra["user"] = user
    if group is not None:
        extra["group"] = group
        extra["extra_groups"] = []
    try:
        process = subprocess.Popen(
            argv,
            stdin=follower,
            stdout=follower,
            stderr=follower,
            env=env,
            cwd=cwd,
            start_new_session=True,
            close_fds=True,
            **extra,
        )
    except OSError:
        os.close(leader)
        os.close(follower)
        return NOT_STARTED_EXIT, ""
    os.close(follower)

    def read(wait_s: float):
        ready, _, _ = select.select([leader], [], [], wait_s)
        if not ready:
            return None
        try:
            return os.read(leader, AGENT_ANSWER_READ_BYTES)
        except OSError:
            # Linux answers EIO once the other side has gone: the end.
            return b""

    def write(data: bytes) -> None:
        os.write(leader, data)

    started = time.monotonic()
    try:
        output = answer_on_prompt(
            read,
            write,
            prompt=prompt,
            answer=answer,
            deadline=started + timeout_s,
            prompt_deadline=started + min(timeout_s, AGENT_ANSWER_PROMPT_TIMEOUT_S),
        )
    finally:
        os.close(leader)
    try:
        code = process.wait(timeout=AGENT_ANSWER_EXIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait()
    return code, output.decode("utf-8", "replace")
