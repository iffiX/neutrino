"""What every module's provisioner reports back to the installer.

The provisioners themselves live with their modules — ``modules/gitea``
installs Gitea, ``modules/netbird`` installs NetBird — since installing a
thing is that thing's business. What they share is only the shape of their
answer, and each is idempotent: asked twice, the second call finds its work
already done.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class ProvisionResult:
    """What a provisioner did.

    Attributes:
        is_changed: Whether anything on the system was altered.
        message: Short description for the installer's output.
    """

    is_changed: bool
    message: str


def say(report: Callable[[str], None] | None, message: str) -> None:
    """Tell whoever is watching, if anyone is.

    Provisioners run from the installer, where a reporter prints steps, and
    from the panel, where a task stream carries them to the browser — and
    sometimes from neither. The callback is optional so a provisioner never
    has to care which.

    Args:
        report: The caller's line sink, or None.
        message: One line of progress.
    """
    if report is not None:
        report(message)
