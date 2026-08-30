"""Fixed values of the web layer."""

from pathlib import Path

from neutrino_hub.utils.constants import UTILS_DATA_DIR

WEB_FRONTEND_DIST_DIR = UTILS_DATA_DIR / "frontend"
WEB_SESSION_COOKIE = "neutrino_session"

# Password hashing. scrypt comes from the standard library, so the appliance
# needs no native crypto dependency to store an admin password safely.
WEB_SCRYPT_SALT_BYTES = 16
WEB_SCRYPT_COST = 2**15
WEB_SCRYPT_BLOCK_SIZE = 8
WEB_SCRYPT_PARALLELISM = 1
WEB_SCRYPT_KEY_BYTES = 32
# OpenSSL refuses a derivation that needs more than its default 32 MiB, and the
# cost above needs exactly that much, so the limit is raised explicitly.
WEB_SCRYPT_MAX_MEMORY_BYTES = 64 * 1024 * 1024

# Login throttling: a personal appliance needs no more than a slow trickle of
# attempts, and this keeps a LAN-side brute force pointless.
WEB_LOGIN_ATTEMPT_LIMIT = 5
# After the free failures are spent, each further failed attempt locks login
# for the next step of this ladder, topping out at a day.
WEB_LOGIN_LOCKOUT_STEPS_S = (30, 60, 300, 3600, 86400)
# The lockout lives in a root-owned file on tmpfs, so it survives a panel
# restart but not a reboot — and the owner clears it with ./unlock.sh, which
# simply deletes the file.
WEB_LOGIN_LOCKOUT_STATE_PATH = Path("/run/neutrino/login_lockout.json")

WEB_STATS_PUSH_INTERVAL_S = 2.0
WEB_DNS_LOG_PATH = Path("/var/log/neutrino/dnsmasq.log")
