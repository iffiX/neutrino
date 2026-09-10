"""The contract every platform implements.

The contract names intents, not mechanisms: where this person's configuration
lives; where the control socket is and who its peer is; judge a proposed
mount location; attach, detach and query a share at a location; open a link;
start a windowed program. A new platform is a new class, and nothing above
this seam changes. The client runs as the person, so every file operation is
the standard library's own on the person's home.

Invoking a capability a platform does not have raises
:class:`PlatformUnsupportedError`, whose ``code`` every surface reports.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import re
import subprocess
import time
import webbrowser

from neutrino_client.exceptions import (
    ControlSocketUnavailableError,
    PlatformUnsupportedError,
)

# A console tool started from the windowless resident would open a console
# of its own; the flag is Windows' and zero anywhere else.
CREATE_NO_WINDOW = 0x08000000


def run_quietly(
    command: list,
    *,
    input: "str | None" = None,
    timeout_s: float,
    encoding: "str | None" = None,
) -> "subprocess.CompletedProcess":
    """Run one tool with no console of its own, its output captured as text.

    Args:
        command: Argument vector.
        input: Sent to standard input; None sends nothing.
        timeout_s: How long the tool may take.
        encoding: The output's encoding; None takes the locale's.

    Returns:
        The completed process.

    Raises:
        OSError: When the tool cannot be started.
        subprocess.SubprocessError: When it times out or the run fails.
    """
    return subprocess.run(
        command,
        input=input,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        timeout=timeout_s,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class ClientPlatform:
    """What the client asks of the operating system, behind one seam.

    The base class is also the honest answer for a platform the client does
    not know: it refuses every capability.
    """

    os_name = ""
    # What a mount location is on this platform: a directory path, or a
    # drive letter on Windows. Surfaces grey the directory browser off it.
    mount_location_shape = "path"

    def config_dir(self) -> str:
        """Where this person's client keeps its files.

        Returns:
            The absolute directory path.

        Raises:
            PlatformUnsupportedError: When the platform has no such place.
        """
        raise PlatformUnsupportedError("no configuration directory here")

    def home(self) -> str:
        """This person's home directory."""
        return os.path.expanduser("~")

    def control_socket_path(self) -> str:
        """Where this person's control socket lives.

        Returns:
            The absolute socket path or pipe name.

        Raises:
            ControlSocketUnavailableError: When the platform cannot place one.
        """
        raise ControlSocketUnavailableError("no control socket here")

    def read_peer_identity(self, connection) -> dict:
        """The kernel-reported identity of a control socket peer.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_same_user"}``; ``uid`` is -1 where the
            platform reports names, not uids.

        Raises:
            PlatformUnsupportedError: When the platform cannot read peers.
        """
        raise PlatformUnsupportedError("cannot read a peer identity here")

    def validate_mount_location(self, *, location: str) -> "dict | None":
        """Judge a proposed mount location by this platform's own rules.

        Args:
            location: The proposed location, as typed.

        Returns:
            None when the location is acceptable, otherwise the typed
            refusal ``{"code", "params"}``.
        """
        if not location or not os.path.isabs(location):
            return {"code": "mountpoint_invalid", "params": {}}
        return None

    def prepare_mount_location(self, *, location: str) -> "dict | None":
        """Have a mount location ready for an attach.

        Args:
            location: The mount location.

        Returns:
            None when the location is ready, otherwise the typed refusal
            ``{"code", "params"}``.
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
            self.make_directory(path=location)
        except OSError:
            return {"code": "fs_refused", "params": {}}
        return None

    def attach_share(
        self, *, share_url: str, location: str, credentials_path: str
    ) -> None:
        """Attach a published share at a location with a kept login.

        Args:
            share_url: The share, as ``//host/name``.
            location: Where the share appears.
            credentials_path: The credentials file the login is read from.

        Raises:
            PlatformUnsupportedError: When the platform cannot attach.
            ShareAttachError: When the tooling is missing, the credentials
                file is gone, the person declined, or the mount refuses.
        """
        raise PlatformUnsupportedError("cannot attach a share here")

    def detach_share(self, *, location: str) -> None:
        """Detach a share attached at a location.

        Args:
            location: Where the share is attached.

        Raises:
            PlatformUnsupportedError: When the platform cannot detach.
            ShareAttachError: When the unmount refuses.
        """
        raise PlatformUnsupportedError("cannot detach a share here")

    def is_share_attached(self, *, location: str) -> bool:
        """Whether a share is attached at a location.

        Args:
            location: The location to ask about.

        Raises:
            PlatformUnsupportedError: When the platform cannot answer.
        """
        raise PlatformUnsupportedError("cannot query shares here")

    def has_mount_tooling(self) -> bool:
        """Whether this machine can attach a share right now."""
        return True

    def write_share_credentials(
        self, *, credentials_path: str, username: str, password: str
    ) -> None:
        """Keep a share's login as a file only this person reads.

        Args:
            credentials_path: Where the file lives.
            username: The share's own username.
            password: The share's own password.
        """
        directory = os.path.dirname(credentials_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
        descriptor = os.open(
            credentials_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"username={username}\npassword={password}\n")

    def mount_location_choices(self) -> list:
        """The mount locations to offer as a fixed set, when there is one.

        Returns:
            Empty where a location is a free-form path; the drive letters
            still open on a platform that mounts at one.
        """
        return []

    def suggest_mount_location(self) -> str:
        """A location to offer before the person types one.

        Returns:
            Empty here: the page composes a path under the home. Windows
            answers with a free drive letter.
        """
        return ""

    def list_directories(self, *, path: str) -> list:
        """The subdirectory names under a directory.

        Args:
            path: The absolute directory path.

        Returns:
            Subdirectory names, sorted, dot names left out.

        Raises:
            OSError: When the directory cannot be listed.
        """
        return sorted(
            entry.name
            for entry in os.scandir(path)
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def make_directory(self, *, path: str) -> None:
        """Create a directory, parents included.

        Args:
            path: The absolute directory path.

        Raises:
            OSError: When the directory cannot be created.
        """
        os.makedirs(path, exist_ok=True)

    def open_url(self, url: str) -> None:
        """Open a link in the person's browser.

        Args:
            url: The link.
        """
        webbrowser.open(url)

    def run_answering(
        self, argv: list, *, prompt: str, answer: str, timeout_s: float
    ) -> tuple:
        """Run a program on a terminal of its own and answer one prompt.

        A tool that asks a question on its terminal and takes no flag in
        its place is given a terminal, and the answer, here.

        Args:
            argv: Argument vector.
            prompt: The text whose arrival is what the answer follows.
            answer: The keystrokes to send, newline included.
            timeout_s: How long the whole run may take.

        Returns:
            ``(returncode, output)``.

        Raises:
            PlatformUnsupportedError: Where no terminal can be made.
        """
        raise PlatformUnsupportedError("no terminal on this platform")

    def start_on_screen(self, argv: list) -> "subprocess.Popen":
        """Start a windowed program on this person's screen.

        Args:
            argv: Argument vector.

        Returns:
            The running process.

        Raises:
            OSError: When the program cannot be started.
        """
        return subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def answer_on_prompt(
    read, write, *, prompt: str, answer: str, deadline: float
) -> bytes:
    """Read a terminal until it ends, answering the prompt once it shows.

    Args:
        read: ``read(wait_s)`` -> bytes; empty at the end, None when nothing
            arrived in time.
        write: ``write(data)`` sends bytes to the terminal.
        prompt: The text the answer follows.
        answer: What to send once the prompt has shown.
        deadline: A ``time.monotonic()`` value past which reading stops.

    Returns:
        Everything the terminal printed.
    """
    output = b""
    marker = prompt.encode("utf-8")
    is_answered = False
    while time.monotonic() < deadline:
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


# What a terminal weaves through its text: cursor moves and colours (CSI),
# titles (OSC, ended by a bell or a string terminator, never spanning past
# the next escape), and the two-byte escapes.
TERMINAL_SEQUENCES = re.compile(
    rb"\x1b\[[0-9;?]*[ -/]*[@-~]"
    rb"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\\\)?"
    rb"|\x1b[@-Z\\\\-_]"
)


def plain_text(output: bytes) -> bytes:
    """A terminal's output with its control sequences taken out.

    Args:
        output: What the terminal printed.

    Returns:
        The text alone, so a prompt is found however it was drawn.
    """
    return TERMINAL_SEQUENCES.sub(b"", output)
