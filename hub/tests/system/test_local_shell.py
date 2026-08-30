"""A shell on the gateway itself, behind a pseudo-terminal.

These start real processes, which is the point: every bug this file exists for
was one that only shows up against a real pty — output buffered until Enter, a
window size the shell never learned, a background job left running after its
tab closed.
"""

import asyncio
import os

import pytest

from neutrino_hub.system.local_shell import (
    LocalShellSession,
    _session_members,
    login_home,
    login_shell,
)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def drain(session: LocalShellSession, want: str, tries: int = 40) -> str:
    """Read until the wanted text appears, or the shell stops producing."""
    seen = ""
    for _ in range(tries):
        try:
            chunk = await asyncio.wait_for(session.read(), timeout=2)
        except asyncio.TimeoutError:
            return seen
        if not chunk:
            return seen
        seen += chunk.decode("utf-8", errors="replace")
        if want in seen:
            return seen
    return seen


# --- Choosing a shell -------------------------------------------------------


def test_a_usable_shell_is_always_named():
    """An appliance has to hand out a prompt even from an odd account."""
    shell = login_shell()

    assert shell.startswith("/")
    assert "nologin" not in shell


def test_a_shell_opens_at_home_not_in_the_install_tree():
    """The panel runs from the checkout; a prompt there invites editing it."""

    # The whole line, since the install tree lives under the home directory
    # here: a bare prefix match would pass from inside the checkout too.
    printed = f"{login_home()}\r\n"

    async def scenario() -> str:
        session = LocalShellSession()
        await session.start()
        try:
            session.write("pwd\n")
            return await drain(session, printed)
        finally:
            await session.close()

    assert printed in asyncio.run(scenario())


# --- The terminal itself ----------------------------------------------------


def test_output_arrives_without_waiting_for_a_newline():
    """The bug that made a terminal look like it was swallowing keystrokes.

    A prompt has no newline after it, so anything that reads by lines shows
    nothing until Enter is pressed — the shell appears dead while it is in fact
    waiting.
    """

    async def scenario() -> str:
        session = LocalShellSession()
        await session.start()
        try:
            for character in "echo hi":
                session.write(character)
                await asyncio.sleep(0.03)
            return await drain(session, "echo hi")
        finally:
            await session.close()

    assert "echo hi" in asyncio.run(scenario())


def test_the_shell_is_told_its_window_size():
    """Without this everything is drawn for 80x24 and full-screen tools break."""

    async def scenario() -> str:
        session = LocalShellSession(rows=30, columns=100)
        await session.start()
        try:
            session.write("stty size\n")
            return await drain(session, "30 100")
        finally:
            await session.close()

    assert "30 100" in asyncio.run(scenario())


def test_a_resize_reaches_a_running_shell():
    async def scenario() -> str:
        session = LocalShellSession()
        await session.start()
        try:
            session.resize(120, 40)
            session.write("stty size\n")
            return await drain(session, "40 120")
        finally:
            await session.close()

    assert "40 120" in asyncio.run(scenario())


def test_the_session_ends_when_the_shell_exits():
    """`exit` must end the terminal rather than leave a dead one on screen."""

    async def scenario() -> bool:
        session = LocalShellSession()
        await session.start()
        try:
            session.write("exit\n")
            await drain(session, "\x00")
            await asyncio.sleep(0.3)
            return session.is_running
        finally:
            await session.close()

    assert asyncio.run(scenario()) is False


# --- Closing a tab leaves nothing behind ------------------------------------


def test_closing_takes_the_background_jobs_with_it():
    """The leak that made the process group the wrong thing to signal.

    Under job control a background job gets a process group of its own, so
    signalling the shell's group leaves it running. On a box with no other
    window into itself those pile up invisibly, one per closed tab. The session
    is the grouping nothing can leave, so the session is what gets swept.
    """

    async def scenario() -> tuple[int, list[int]]:
        session = LocalShellSession()
        await session.start()
        shell_pid = session._process.pid
        session.write("sleep 451 &\n")
        await asyncio.sleep(1.0)
        children = [pid for pid in _session_members(shell_pid) if pid != shell_pid]
        await session.close()
        await asyncio.sleep(0.5)
        return shell_pid, children

    shell_pid, children = asyncio.run(scenario())

    assert children, "the shell started no background job, so nothing was proven"
    assert not alive(shell_pid)
    assert [pid for pid in children if alive(pid)] == []


def test_two_shells_do_not_share_state():
    """Each tab is its own shell, not two views of one."""

    async def scenario() -> str:
        first = LocalShellSession()
        second = LocalShellSession()
        await first.start()
        await second.start()
        try:
            first.write("MARK=alpha\n")
            await asyncio.sleep(0.3)
            second.write("printf 'B<%s>\\n' \"$MARK\"\n")
            # B<> and not B<: the shell echoes the command first, and that
            # echo contains B<%s>, so the shorter marker matches the typing
            # rather than the answer.
            return await drain(second, "B<>")
        finally:
            await first.close()
            await second.close()

    assert "B<>" in asyncio.run(scenario())


@pytest.mark.parametrize("size", [(80, 24), (200, 50)])
def test_a_session_starts_at_the_size_it_is_given(size):
    columns, rows = size

    async def scenario() -> str:
        session = LocalShellSession(rows=rows, columns=columns)
        await session.start()
        try:
            session.write("stty size\n")
            return await drain(session, f"{rows} {columns}")
        finally:
            await session.close()

    assert f"{rows} {columns}" in asyncio.run(scenario())
