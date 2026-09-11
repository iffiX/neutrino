"""Verbose step reporting for the installer.

Presentation only: the installer prints a numbered step per action, says whether
it changed anything or found it already in place, and stops at the first failure
with the command output that explains it. A run started from a browser reports
the same steps to it as well.
"""

import time

from neutrino_hub.web.constants import (
    WEB_SETUP_STEP_DONE,
    WEB_SETUP_STEP_FAILED,
    WEB_SETUP_STEP_RUNNING,
)

import re
import sys
from pathlib import Path

# Colour is for the terminal; the log keeps the words without it.
REPORTER_ANSI = re.compile(r"\033\[[0-9;]*m")

GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class InstallReporter:
    """Prints numbered installation steps with timing and outcome.

    Writes to a file as well as to the terminal, and outlives the terminal. A
    first run reconfigures the interface it is often being watched over, so
    the session can go away in the middle of it — and a run that dies at that
    moment leaves a half-configured machine, which is the one outcome a first
    run must not have. So every line goes to the log first, and a terminal
    that has hung up is written off rather than raised over.
    """

    def __init__(
        self,
        *,
        total_step_count: int,
        is_color_enabled: bool = True,
        log_path: Path | None = None,
    ):
        """
        Args:
            total_step_count: How many steps the run will report, used for the
                ``[3/12]`` counter.
            is_color_enabled: Whether to emit ANSI colour.
            log_path: Where to keep a copy of everything printed, so a run
                whose terminal went away can still be read afterwards.
        """
        self._total_step_count = total_step_count
        self._is_color_enabled = is_color_enabled
        self._step_index = 0
        self._started_at = 0.0
        self._log = _opened(log_path)

    def _say(self, text: str = "", *, end: str = "\n") -> None:
        """Write one line, to the log and to the terminal if there is one.

        Args:
            text: What to write.
            end: What to end it with; empty for a line continued later.
        """
        if self._log is not None:
            try:
                self._log.write(REPORTER_ANSI.sub("", text) + end)
                self._log.flush()
            except OSError:
                self._log = None
        try:
            sys.stdout.write(text + end)
            sys.stdout.flush()
        except (OSError, ValueError):
            # The terminal has gone. The log still has every line, and the run
            # carries on — stopping here is what would leave a box half done.
            pass

    def banner(self, text: str) -> None:
        """Print the run's header.

        Args:
            text: Title line.
        """
        self._say()
        self._say(self._color(f"  {text}", BOLD))
        self._say(self._color("  " + "─" * max(len(text), 40), DIM))
        self._say()

    def start(
        self, description: str, code: str = "", params: dict | None = None
    ) -> None:
        """Announce the next step.

        Args:
            description: What the step is about to do.
            code: The step's name for a browser to word itself; the terminal
                prints ``description`` either way.
            params: The values that wording names.
        """
        del code, params
        self._step_index += 1
        self._started_at = time.monotonic()
        counter = f"[{self._step_index}/{self._total_step_count}]"
        self._say(f"  {self._color(counter, BLUE)} {description} ... ", end="")

    def done(self, note: str = "") -> None:
        """Report the current step succeeded.

        There is no third outcome. A step that found its work already done
        succeeded, and saying so in another colour makes a column of green
        read as though something in it went wrong — which is what the note
        beside it is for.

        Args:
            note: Short detail, for example a version number or what was
                already in place.
        """
        self._finish("OK", GREEN, note)

    def failed(self, message: str) -> None:
        """Report the current step failed.

        Args:
            message: The error text to show under the step.
        """
        self._finish("FAILED", RED, "")
        self._say()
        for line in message.strip().splitlines():
            self._say(f"      {self._color(line, RED)}")
        self._say()

    def blank(self) -> None:
        """One empty line, for separating what is said from what is done."""
        self._say()

    def note(self, text: str) -> None:
        """Print an indented informational line between steps.

        Args:
            text: The message.
        """
        self._say(f"      {self._color(text, DIM)}")

    def checklist(self, title: str, items: list[str]) -> None:
        """Print the closing to-do list.

        Args:
            title: Heading for the list.
            items: One line per remaining manual action.
        """
        self._say()
        self._say(self._color(f"  {title}", BOLD))
        for item in items:
            self._say(f"    {self._color('•', BLUE)} {item}")
        self._say()

    def _finish(self, label: str, color: str, note: str) -> None:
        elapsed = time.monotonic() - self._started_at
        suffix = f" {self._color(f'({note})', DIM)}" if note else ""
        timing = self._color(f"{elapsed:5.1f}s", DIM)
        self._say(f"{self._color(label, color)}{suffix} {timing}")

    def _color(self, text: str, code: str) -> str:
        if not self._is_color_enabled:
            return text
        return f"{code}{text}{RESET}"


class InstallSessionReporter(InstallReporter):
    """The same lines, and a copy of them a browser can read.

    Setup run from a browser still prints to whoever started it: one machine
    is being changed, and the terminal that started the change is where a
    failure has to be readable. This adds the second audience rather than
    replacing the first.
    """

    def __init__(
        self,
        *,
        session,
        total_step_count: int,
        is_color_enabled: bool = True,
        log_path: Path | None = None,
    ):
        """
        Args:
            session: Where the browser reads from.
            total_step_count: How many steps the run will report.
            is_color_enabled: Whether to emit ANSI colour.
            log_path: Where to keep a copy of everything printed.
        """
        super().__init__(
            total_step_count=total_step_count,
            is_color_enabled=is_color_enabled,
            log_path=log_path,
        )
        self._session = session
        self._code = ""
        self._params: dict = {}

    def start(
        self, description: str, code: str = "", params: dict | None = None
    ) -> None:
        """Announce the next step to both.

        Args:
            description: What the step is about to do.
            code: The step's name, which is what the browser words.
            params: The values that wording names.
        """
        self._code = code or description
        self._params = dict(params or {})
        self._session.step(self._code, WEB_SETUP_STEP_RUNNING, params=self._params)
        super().start(description)

    def done(self, note: str = "") -> None:
        """Report the current step succeeded, here and in the browser.

        Args:
            note: Short detail, for example a version number or what was
                already in place.
        """
        self._session.step(self._code, WEB_SETUP_STEP_DONE, note, params=self._params)
        super().done(note)

    def failed(self, message: str) -> None:
        """Report the current step failed.

        Args:
            message: The error text to show under the step.
        """
        self._session.step(
            self._code, WEB_SETUP_STEP_FAILED, message, params=self._params
        )
        super().failed(message)

    def blank(self) -> None:
        """One empty line, for separating what is said from what is done."""
        self._say()

    def note(self, text: str) -> None:
        """Print an aside, and keep it where the browser can read it.

        Args:
            text: The message.
        """
        self._session.note(text)
        super().note(text)


def _opened(path: Path | None):
    """Open the log to append to, or nothing when there is nowhere to write.

    Args:
        path: Where the copy goes, or None for a run that keeps none.

    Returns:
        The open file, or None — a log that cannot be opened is not a reason
        to refuse to run.
    """
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("a", encoding="utf-8")
    except OSError:
        return None
