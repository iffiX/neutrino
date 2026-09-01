# What a device is addressed by, everywhere. Six hexadecimal pairs, colon or
# hyphen separated, in any case; the registry lowercases and normalises on the
# way in. Anything else is not an address this box can wake, pin a host key
# against, or match a scan to, so it is refused rather than stored.
DEVICE_MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$"

DEVICE_LAN_SCAN_TIMEOUT_S = 30
DEVICE_WOL_PORT = 9
# Pure Python over the network; nothing architecture-bound is installed here.
DEVICE_SUPPORTED_ARCHITECTURES = ("*",)

# What a command reports when the device could not be asked at all: it was
# off, the credentials were refused, the host key had changed. The shell's own
# "command not found" is 127 and a refused connection has no status of its
# own, so one is chosen here — and it is not a failure of the command, which
# is what makes it worth telling apart.
SSH_UNREACHABLE_STATUS = 255
