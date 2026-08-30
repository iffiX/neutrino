from pathlib import Path

# The whole of smb.conf is generated — the stock file ships printer shares an
# appliance has no business serving — and the live path is a symlink into the
# generated tree, the same shape dnsmasq uses.
SAMBA_CONF_LINK_PATH = Path("/etc/samba/smb.conf")
SAMBA_GENERATED_NAME = "smb.conf"

# Every panel-created account joins this group; share directories are owned by
# it with setgid, so files members create stay writable to the others and
# permissions never fight. It is Ubuntu's own group for exactly this.
SAMBA_GROUP = "sambashare"

SAMBA_DEFAULT_SHARE_DIR = Path("/srv/share")
# Arrives through apt, which picks the machine's build.
SAMBA_SUPPORTED_ARCHITECTURES = ("*",)
