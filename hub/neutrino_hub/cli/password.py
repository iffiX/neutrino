"""Reading and storing the panel password.

``nhub setup`` and ``nhub reset password`` take it on the same terms: prompted
twice, or read from standard input for an unattended run. It is never an
argument — an argument is visible in ``ps`` to every user on the machine for as
long as the command runs, and stays in the shell history afterwards.

Eight characters is the whole of the rule. Everything else — mixing letters,
numbers and symbols — is a preference, said out loud where it is asked for and
never turned into a refusal.
"""

import getpass
import secrets
import sys

from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.web.auth import hash_password

# --- config ---
PASSWORD_MIN_LENGTH = 8
PASSWORD_SETTINGS_FILE = "web/settings.json"  # scan: allow
PASSWORD_HASH_FIELD = "admin_password_hash"  # scan: allow
PASSWORD_SECRET_FIELD = "session_secret"  # scan: allow
# What the committed example carries in both fields until a real one lands.
PASSWORD_PLACEHOLDER_PREFIX = "PLACEHOLDER"  # scan: allow
PASSWORD_SESSION_SECRET_BYTES = 32


class PasswordRefused(ValueError):
    """The password given cannot be used."""


def read_new_password(*, is_stdin: bool = False) -> str:
    """Ask for a password, or take one from standard input.

    Args:
        is_stdin: Read one line from standard input instead of prompting.

    Returns:
        The password.

    Raises:
        PasswordRefused: When it is too short, or the two prompts disagree.
    """
    try:
        if is_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Panel password: ")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise PasswordRefused(
                f"too short: use at least {PASSWORD_MIN_LENGTH} characters, "
                "and better for mixing letters, numbers and symbols"
            )
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
    """Write the password's hash, and a session secret if there is none yet.

    Args:
        password: The password to store the hash of. The plaintext is never
            written anywhere.
    """
    settings = read_config(PASSWORD_SETTINGS_FILE)
    settings[PASSWORD_HASH_FIELD] = hash_password(password)
    if _is_placeholder(settings.get(PASSWORD_SECRET_FIELD, "")):
        settings[PASSWORD_SECRET_FIELD] = secrets.token_hex(
            PASSWORD_SESSION_SECRET_BYTES
        )
    write_config(PASSWORD_SETTINGS_FILE, settings)


def clear_password() -> None:
    """Return the password and the session secret to the example's placeholders."""
    settings = read_config(PASSWORD_SETTINGS_FILE)
    settings[PASSWORD_HASH_FIELD] = f"{PASSWORD_PLACEHOLDER_PREFIX}_ARGON2ID_HASH"
    settings[PASSWORD_SECRET_FIELD] = f"{PASSWORD_PLACEHOLDER_PREFIX}_RANDOM_HEX"
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
