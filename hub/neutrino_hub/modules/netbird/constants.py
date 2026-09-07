from pathlib import Path

# The vendor install script selects the right package for the machine.
NETBIRD_SUPPORTED_ARCHITECTURES = ("*",)

# Where the daemon keeps what it was last told, and how the current profile is
# named. Read rather than written: this is the vendor's file, and the only
# thing asked of it is what NetBird believes right now, so that setting it
# again when it already agrees does not cost a reconnection. The older
# single-file layout is still read, because a box that upgraded NetBird keeps
# it. Both are absent on a machine that never enrolled, which reads as
# "unknown" and is answered by setting it rather than assuming.
NETBIRD_STATE_DIR = Path("/var/lib/netbird")
NETBIRD_ACTIVE_PROFILE_PATH = NETBIRD_STATE_DIR / "active_profile.json"
NETBIRD_LEGACY_CONFIG_PATH = Path("/etc/netbird/config.json")
NETBIRD_BLOCK_INBOUND_KEY = "BlockInbound"

# `netbird up` re-establishes the session, so it is given the same room as an
# enrollment rather than a command's usual seconds.
NETBIRD_INBOUND_TIMEOUT_S = 60
