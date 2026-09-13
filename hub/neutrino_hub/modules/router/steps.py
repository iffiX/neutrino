"""What one step of making the routing state real did.

Every step the router reconciler runs reports one of these, so a step that
failed is named beside the steps that went on without it.
"""

import subprocess
from dataclasses import dataclass, field

from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_UNCHANGED,
)
from neutrino_hub.utils.subprocess_run import command_failure_text


@dataclass
class RouterStepResult:
    """One step's outcome.

    Attributes:
        name: What the step makes true, for example ``interface enp1s0``.
        state: ``applied``, ``unchanged``, ``pending`` or ``failed``.
        code: Why it is pending or failed; empty otherwise.
        detail: The tool's words, or what the step waits for.
        changes: One line per change the step made.
    """

    name: str
    state: str
    code: str = ""
    detail: str = ""
    changes: list = field(default_factory=list)

    @property
    def is_failed(self) -> bool:
        """Whether the step was tried and refused."""
        return self.state == ROUTER_STEP_FAILED

    def describe(self) -> str:
        """The step as one line for a journal or a terminal."""
        head = f"{self.name}: {self.state}"
        if self.code:
            head = f"{head} {self.code}"
        detail = self.detail or "; ".join(self.changes)
        return f"{head}: {detail}" if detail else head


def run_step(name: str, action) -> RouterStepResult:
    """Run one step and report it, whatever it does.

    Args:
        name: The step's name.
        action: Called with nothing; returns the lines it changed, or None.

    Returns:
        ``applied`` when it changed something, ``unchanged`` when it did not,
        ``failed`` when a command or a file refused.
    """
    try:
        changes = list(action() or [])
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        return RouterStepResult(
            name=name,
            state=ROUTER_STEP_FAILED,
            code=ROUTER_CODE_COMMAND_FAILED,
            detail=command_failure_text(error),
        )
    return RouterStepResult(
        name=name,
        state=ROUTER_STEP_APPLIED if changes else ROUTER_STEP_UNCHANGED,
        changes=changes,
    )
