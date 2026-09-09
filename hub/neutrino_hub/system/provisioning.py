"""What every module's provisioner reports back to the installer.

The provisioners themselves live with their modules, ``modules/netbird``
installs NetBird and ``modules/cliproxyapi`` the AI gateway, since
installing a thing is that thing's business. What they share is only the shape of their
answer, and each is idempotent: asked twice, the second call finds its work
already done.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ProvisionConsent:
    """Something installing would do that has to be agreed to first.

    Not every consequence needs asking. Adding the repository a distribution
    keeps a package in is part of installing it, and somebody who pressed
    install has said so. Compiling a kernel module against the running kernel
    is a different act, and so is replacing a service the machine already
    runs.

    Attributes:
        code: What kind of consequence this is. The panel turns it into a
            sentence; this layer never writes one, so the wording can be
            translated and this stays a fact.
        detail: The values that sentence needs, such as which packages and
            which kernel.
    """

    code: str
    detail: dict = field(default_factory=dict)


@dataclass
class ProvisionPlan:
    """What installing a module on this machine would actually do.

    A module answers this before it is asked to install, so the panel can put
    anything surprising in front of a person while there is still a decision
    to make.

    Attributes:
        consents: What has to be agreed to. Empty is the ordinary case and
            means install proceeds on the press that started it.
    """

    consents: tuple = ()

    @property
    def is_consent_needed(self) -> bool:
        """Whether the panel has to ask before this install runs."""
        return bool(self.consents)


def plan_for(provisioner) -> ProvisionPlan:
    """What a provisioner says installing would do on this machine.

    Most modules install packages and nothing else, and say so by not
    answering at all.

    Args:
        provisioner: The module's provisioner.

    Returns:
        Its plan, or an empty one.
    """
    method = getattr(provisioner, "plan", None)
    return method() if method is not None else ProvisionPlan()


class ProvisionNotConsented(RuntimeError):
    """Raised when an install that needs agreement is run without it."""


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
