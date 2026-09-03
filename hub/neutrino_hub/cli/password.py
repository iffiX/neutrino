"""Reading and storing the panel password.

``nhub setup`` and ``nhub reset password`` take it on the same terms: prompted
twice, or read from standard input for an unattended run. It is never an
argument — an argument is visible in ``ps`` to every user on the machine for as
long as the command runs, and stays in the shell history afterwards.

The rules themselves live in :mod:`neutrino_hub.utils.passwords`; this file
prompts, words a refusal, and stores what was accepted.
"""

import getpass
import sys

from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.passwords import (
    PASSWORDS_ERROR_TOO_SHORT,
    PASSWORDS_PANEL_RULES,
    PasswordRuleError,
    PasswordRules,
    validate,
)
from neutrino_hub.web.auth import hash_password

# --- config ---
PASSWORD_SETTINGS_FILE = "web/settings.json"  # scan: allow
PASSWORD_HASH_FIELD = "admin_password_hash"  # scan: allow
# What the committed example carries until a real hash lands.
PASSWORD_PLACEHOLDER_PREFIX = "PLACEHOLDER"  # scan: allow


class PasswordRefused(ValueError):
    """The password given cannot be used."""


def worded_refusal(error: PasswordRuleError) -> str:
    """One sentence for a rule refusal, for the terminal askers.

    Args:
        error: What :func:`neutrino_hub.utils.passwords.validate` raised.

    Returns:
        The sentence to show.
    """
    if error.code == PASSWORDS_ERROR_TOO_SHORT:
        return f"too short: use at least {error.params['min_length']} characters"
    return "missing a " + ", a ".join(error.params.get("classes", []))


def read_new_password(
    *,
    is_stdin: bool = False,
    prompt: str = "Panel password",
    rules: PasswordRules = PASSWORDS_PANEL_RULES,
) -> str:
    """Ask for a password, or take one from standard input.

    Args:
        is_stdin: Read one line from standard input instead of prompting.
        prompt: What to call the secret being asked for.
        rules: The rule set to judge it by.

    Returns:
        The password.

    Raises:
        PasswordRefused: When the rules refuse it, or the two prompts
            disagree.
    """
    try:
        if is_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass(f"{prompt}: ")
        try:
            validate(password, rules)
        except PasswordRuleError as error:
            raise PasswordRefused(worded_refusal(error)) from error
        if not is_stdin and password != getpass.getpass("Repeat: "):
            raise PasswordRefused("the two passwords do not match")
    except EOFError as error:
        # Prompting with nothing to read from is an unattended run that forgot
        # --password-stdin, and a traceback is no way to say so.
        raise PasswordRefused(
            "there is nothing to read a password from; use --stdin"
        ) from error
    return password


def store_password(password: str) -> None:
    """Write the password's hash.

    Args:
        password: The password to store the hash of. The plaintext is never
            written anywhere.
    """
    settings = read_config(PASSWORD_SETTINGS_FILE)
    settings[PASSWORD_HASH_FIELD] = hash_password(password)
    write_config(PASSWORD_SETTINGS_FILE, settings)


def clear_password() -> None:
    """Return the password to the example's placeholder."""
    settings = read_config(PASSWORD_SETTINGS_FILE)
    settings[PASSWORD_HASH_FIELD] = f"{PASSWORD_PLACEHOLDER_PREFIX}_ARGON2ID_HASH"
    write_config(PASSWORD_SETTINGS_FILE, settings)


def is_password_set() -> bool:
    """Whether somebody has already chosen a panel password.

    This is what makes ``nhub setup`` a thing that runs once: a box with a
    password is a box somebody configured.

    Returns:
        True when the settings hold a real hash rather than the example's
        placeholder, and False when there are no settings at all.
    """
    try:
        settings = read_config(PASSWORD_SETTINGS_FILE)
    except (FileNotFoundError, ValueError):
        return False
    return not _is_placeholder(settings.get(PASSWORD_HASH_FIELD, ""))


def _is_placeholder(value: str) -> bool:
    """Whether a settings field still carries what the example shipped."""
    return not value or value.startswith(PASSWORD_PLACEHOLDER_PREFIX)
