"""The rules a password or passphrase is judged by, in one place.

Two rule sets: the panel password's, and the vault master passphrase's. The
terminal wizard, the browser wizard's backend and the settings API all judge
against the same constants here, so no asker can accept what another would
refuse.
"""

import math
import string
from dataclasses import dataclass

from neutrino_hub.exceptions import PasswordRefusedError

# The character classes a password can draw on, each with the pool size it
# adds to a guesser's search space. The symbol pool is the printable ASCII
# characters the other three leave over.
PASSWORDS_CLASSES = (
    ("lowercase", frozenset(string.ascii_lowercase), 26),
    ("uppercase", frozenset(string.ascii_uppercase), 26),
    ("digit", frozenset(string.digits), 10),
    ("symbol", None, 33),
)

PASSWORDS_ERROR_TOO_SHORT = "password_too_short"
PASSWORDS_ERROR_MISSING_CLASSES = "password_missing_classes"


@dataclass(frozen=True)
class PasswordRules:
    """What one kind of password must satisfy to be accepted.

    Attributes:
        min_length: The shortest password the rule set accepts.
        is_every_class_required: Whether all four character classes must
            appear.
    """

    min_length: int
    is_every_class_required: bool

    def to_dict(self) -> dict:
        """Serialize for an asker that runs somewhere else.

        Returns:
            A JSON-ready object.
        """
        return {
            "min_length": self.min_length,
            "is_every_class_required": self.is_every_class_required,
        }


PASSWORDS_PANEL_RULES = PasswordRules(min_length=8, is_every_class_required=False)
PASSWORDS_MASTER_RULES = PasswordRules(min_length=16, is_every_class_required=True)


def validate(password: str, rules: PasswordRules) -> None:
    """Judge a password against one rule set.

    Args:
        password: The candidate.
        rules: The rule set to judge by.

    Raises:
        PasswordRefusedError: With ``password_too_short`` and the required
            length, or ``password_missing_classes`` and the classes it lacks.
    """
    if len(password) < rules.min_length:
        raise PasswordRefusedError(
            PASSWORDS_ERROR_TOO_SHORT, {"min_length": rules.min_length}
        )
    if rules.is_every_class_required:
        present = _classes_of(password)
        missing = [name for name, _, _ in PASSWORDS_CLASSES if name not in present]
        if missing:
            raise PasswordRefusedError(
                PASSWORDS_ERROR_MISSING_CLASSES, {"classes": missing}
            )


def entropy_bits(password: str) -> float:
    """Estimate a password's strength against blind guessing.

    The estimate assumes the guesser knows which character classes appear:
    the length times the bits per character of the combined pool.

    Args:
        password: The candidate.

    Returns:
        The estimated bits, 0.0 for an empty password.
    """
    if not password:
        return 0.0
    present = _classes_of(password)
    pool = sum(size for name, _, size in PASSWORDS_CLASSES if name in present)
    return len(password) * math.log2(pool)


def _classes_of(password: str) -> set[str]:
    """The character classes a password draws on.

    Args:
        password: The candidate.

    Returns:
        The class names present.
    """
    present = set()
    for character in password:
        for name, members, _ in PASSWORDS_CLASSES:
            if members is not None and character in members:
                present.add(name)
                break
        else:
            present.add("symbol")
    return present
