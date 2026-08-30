"""Password hashing and session handling for the panel.

One admin password guards the whole panel. It is stored only as a scrypt hash,
and sessions are opaque random tokens held in memory, so a restart logs everyone
out and nothing about the password survives on disk in a reversible form.
"""

import hashlib
import hmac
import json
import math
import secrets
import time
from dataclasses import dataclass

from neutrino_hub.web.constants import (
    WEB_LOGIN_ATTEMPT_LIMIT,
    WEB_LOGIN_LOCKOUT_STATE_PATH,
    WEB_LOGIN_LOCKOUT_STEPS_S,
    WEB_SCRYPT_BLOCK_SIZE,
    WEB_SCRYPT_COST,
    WEB_SCRYPT_KEY_BYTES,
    WEB_SCRYPT_MAX_MEMORY_BYTES,
    WEB_SCRYPT_PARALLELISM,
    WEB_SCRYPT_SALT_BYTES,
)

HASH_PREFIX = "scrypt"


def hash_password(password: str) -> str:
    """Hash a password for storage in ``config/web/settings.json``.

    Args:
        password: The plaintext password. It is never stored or logged.

    Returns:
        An encoded hash of the form ``scrypt$<salt hex>$<key hex>``.
    """
    salt = secrets.token_bytes(WEB_SCRYPT_SALT_BYTES)
    key = _derive_key(password, salt)
    return f"{HASH_PREFIX}${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Check a password against a stored hash in constant time.

    Args:
        password: The plaintext attempt.
        encoded_hash: The value stored in the settings file.

    Returns:
        True when the password matches. A malformed or placeholder hash returns
        False rather than raising, so an unconfigured panel simply refuses every
        login instead of erroring.
    """
    parts = encoded_hash.split("$")
    if len(parts) != 3 or parts[0] != HASH_PREFIX:
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    return hmac.compare_digest(_derive_key(password, salt), expected)


@dataclass
class Session:
    """One logged-in browser session.

    Attributes:
        token: Opaque session identifier stored in the cookie.
        expires_at: Unix time after which the session is no longer valid.
    """

    token: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        """Whether this session has passed its expiry."""
        return time.time() >= self.expires_at


class SessionStore:
    """Holds live sessions and throttles failed logins.

    Sessions live in memory only. That is deliberate for a single-user
    appliance: restarting the panel is a clean way to revoke everything, and no
    session material ever reaches disk.
    """

    def __init__(self, *, password_hash: str, session_ttl_hours: int):
        """
        Args:
            password_hash: The stored hash from the settings file.
            session_ttl_hours: How long a session stays valid.
        """
        self._password_hash = password_hash
        self._session_ttl_s = session_ttl_hours * 3600
        self._sessions: dict[str, Session] = {}
        self._failed_attempt_count = 0
        self._lockout_count = 0
        self._locked_until = 0.0
        self._is_state_on_disk = False
        self._load_lockout()

    def login(self, password: str) -> str | None:
        """Try to start a session.

        Args:
            password: The submitted password.

        Returns:
            A new session token, or None when the password is wrong or the
            panel is currently locked out after repeated failures.
        """
        if self.lockout_remaining_s() > 0:
            return None
        if not verify_password(password, self._password_hash):
            self._register_failure()
            return None
        self._failed_attempt_count = 0
        self._lockout_count = 0
        self._locked_until = 0.0
        WEB_LOGIN_LOCKOUT_STATE_PATH.unlink(missing_ok=True)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = Session(
            token=token, expires_at=time.time() + self._session_ttl_s
        )
        return token

    def logout(self, token: str) -> None:
        """End one session.

        Args:
            token: The session token to drop; unknown tokens are ignored.
        """
        self._sessions.pop(token, None)

    def is_valid(self, token: str | None) -> bool:
        """Whether a token names a live session.

        Args:
            token: The cookie value, or None when absent.

        Returns:
            True when the session exists and has not expired.
        """
        if not token:
            return False
        session = self._sessions.get(token)
        if session is None:
            return False
        if session.is_expired:
            self._sessions.pop(token, None)
            return False
        return True

    def update_password_hash(self, password_hash: str) -> None:
        """Adopt a new password and invalidate every existing session.

        Args:
            password_hash: The newly stored hash.
        """
        self._password_hash = password_hash
        self._sessions.clear()

    def lockout_remaining_s(self) -> int:
        """How much longer login is refused after repeated failures.

        The lockout's persistent half is a file on tmpfs; deleting it —
        which is all ``unlock.sh`` does — clears the lockout and the failure
        history together, right here on the next check.

        Returns:
            Whole seconds left, 0 when login is open.
        """
        if self._is_state_on_disk and not WEB_LOGIN_LOCKOUT_STATE_PATH.exists():
            self._failed_attempt_count = 0
            self._lockout_count = 0
            self._locked_until = 0.0
            self._is_state_on_disk = False
            return 0
        return max(0, math.ceil(self._locked_until - time.time()))

    def _register_failure(self) -> None:
        """Count a failure, and past the free ones, lock for the next step.

        The free attempts are a courtesy for typos. Once they are spent,
        every further failure locks immediately and for longer — 30 seconds
        up to a day — so a brute force gets five guesses cheap and then a
        handful more per day.
        """
        self._failed_attempt_count += 1
        if self._failed_attempt_count > WEB_LOGIN_ATTEMPT_LIMIT:
            step_index = min(self._lockout_count, len(WEB_LOGIN_LOCKOUT_STEPS_S) - 1)
            self._lockout_count += 1
            self._locked_until = time.time() + WEB_LOGIN_LOCKOUT_STEPS_S[step_index]
        self._save_lockout()

    def _save_lockout(self) -> None:
        try:
            WEB_LOGIN_LOCKOUT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            WEB_LOGIN_LOCKOUT_STATE_PATH.write_text(
                json.dumps(
                    {
                        "failed_attempt_count": self._failed_attempt_count,
                        "lockout_count": self._lockout_count,
                        "locked_until": self._locked_until,
                    }
                ),
                encoding="utf-8",
            )
            self._is_state_on_disk = True
        except OSError:
            # Unwritable state degrades to memory-only: the lockout still
            # holds for this process, only the unlock file and the restart
            # persistence are lost.
            self._is_state_on_disk = False

    def _load_lockout(self) -> None:
        try:
            state = json.loads(WEB_LOGIN_LOCKOUT_STATE_PATH.read_text(encoding="utf-8"))
            self._failed_attempt_count = int(state.get("failed_attempt_count", 0))
            self._lockout_count = int(state.get("lockout_count", 0))
            self._locked_until = float(state.get("locked_until", 0.0))
            self._is_state_on_disk = True
        except (OSError, ValueError):
            pass


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=WEB_SCRYPT_COST,
        r=WEB_SCRYPT_BLOCK_SIZE,
        p=WEB_SCRYPT_PARALLELISM,
        maxmem=WEB_SCRYPT_MAX_MEMORY_BYTES,
        dklen=WEB_SCRYPT_KEY_BYTES,
    )
