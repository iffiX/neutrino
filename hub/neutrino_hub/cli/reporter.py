"""Verbose step reporting for the installer.

Presentation only: the installer prints a numbered step per action, says whether
it changed anything or found it already in place, and stops at the first failure
with the command output that explains it.
"""

import time

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class InstallReporter:
    """Prints numbered installation steps with timing and outcome."""

    def __init__(self, *, total_step_count: int, is_color_enabled: bool = True):
        """
        Args:
            total_step_count: How many steps the run will report, used for the
                ``[3/12]`` counter.
            is_color_enabled: Whether to emit ANSI colour.
        """
        self._total_step_count = total_step_count
        self._is_color_enabled = is_color_enabled
        self._step_index = 0
        self._started_at = 0.0

    def banner(self, text: str) -> None:
        """Print the run's header.

        Args:
            text: Title line.
        """
        print()
        print(self._color(f"  {text}", BOLD))
        print(self._color("  " + "─" * max(len(text), 40), DIM))
        print()

    def start(self, description: str) -> None:
        """Announce the next step.

        Args:
            description: What the step is about to do.
        """
        self._step_index += 1
        self._started_at = time.monotonic()
        counter = f"[{self._step_index}/{self._total_step_count}]"
        print(f"  {self._color(counter, BLUE)} {description} ... ", end="", flush=True)

    def done(self, note: str = "") -> None:
        """Report the current step succeeded and changed something.

        Args:
            note: Short detail, for example a version number.
        """
        self._finish("OK", GREEN, note)

    def skipped(self, note: str = "") -> None:
        """Report the current step found its work already done.

        Args:
            note: Short detail explaining what was already in place.
        """
        self._finish("already set", YELLOW, note)

    def failed(self, message: str) -> None:
        """Report the current step failed.

        Args:
            message: The error text to show under the step.
        """
        self._finish("FAILED", RED, "")
        print()
        for line in message.strip().splitlines():
            print(f"      {self._color(line, RED)}")
        print()

    def note(self, text: str) -> None:
        """Print an indented informational line between steps.

        Args:
            text: The message.
        """
        print(f"      {self._color(text, DIM)}")

    def checklist(self, title: str, items: list[str]) -> None:
        """Print the closing to-do list.

        Args:
            title: Heading for the list.
            items: One line per remaining manual action.
        """
        print()
        print(self._color(f"  {title}", BOLD))
        for item in items:
            print(f"    {self._color('•', BLUE)} {item}")
        print()

    def _finish(self, label: str, color: str, note: str) -> None:
        elapsed = time.monotonic() - self._started_at
        suffix = f" {self._color(f'({note})', DIM)}" if note else ""
        timing = self._color(f"{elapsed:5.1f}s", DIM)
        print(f"{self._color(label, color)}{suffix} {timing}")

    def _color(self, text: str, code: str) -> str:
        if not self._is_color_enabled:
            return text
        return f"{code}{text}{RESET}"
