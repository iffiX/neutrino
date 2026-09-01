# What a device is addressed by, everywhere. Six hexadecimal pairs, colon or
# hyphen separated, in any case; the registry lowercases and normalises on the
# way in. Anything else is not an address this box can wake, pin a host key
# against, or match a scan to, so it is refused rather than stored.
DEVICE_MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$"

DEVICE_LAN_SCAN_TIMEOUT_S = 30
DEVICE_WOL_PORT = 9
# Pure Python over the network; nothing architecture-bound is installed here.
DEVICE_SUPPORTED_ARCHITECTURES = ("*",)
