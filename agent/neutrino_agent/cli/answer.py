"""``nagent answer``: run a program on a terminal of its own and answer one question.

    nagent answer --prompt "(y/N)" --answer y -- <program> <arguments...>

The agent runs this as an account on Windows, inside the one-shot scheduled
task it runs a command as that account with: the pseudo console has to be
made in the account's own task. It prints what the console drew and exits
with the program's exit code. Any account may run it.
"""

import os
import sys

from neutrino_agent.constants import AGENT_STEP_DOWN_TIMEOUT_S

# What Enter is on each kind of terminal.
CONSOLE_ENTER = "\r"
TERMINAL_ENTER = "\n"


def main(*, prompt: str, answer: str, argv: list) -> int:
    """Run the program, answer its question, and print what it drew.

    Args:
        prompt: The text the answer follows.
        answer: The keystrokes to type before Enter.
        argv: The program and its arguments.

    Returns:
        The program's exit code; 2 when no program is named.
    """
    if not argv:
        print("nagent answer needs a program after --", file=sys.stderr)
        return 2
    if os.name == "nt":
        from neutrino_agent.streams.windows_shell import run_answering

        code, output = run_answering(
            argv,
            prompt=prompt,
            answer=answer + CONSOLE_ENTER,
            timeout_s=AGENT_STEP_DOWN_TIMEOUT_S,
            start_dir=os.getcwd(),
        )
    else:
        from neutrino_agent.platforms.answered_run import run_on_pty

        code, output = run_on_pty(
            argv,
            prompt=prompt,
            answer=answer + TERMINAL_ENTER,
            timeout_s=AGENT_STEP_DOWN_TIMEOUT_S,
        )
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
    stream.write(output)
    stream.flush()
    return code
