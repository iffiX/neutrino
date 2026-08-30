from pathlib import Path

# The whole of smb.conf is generated — the stock file ships printer shares an
# appliance has no business serving — and the live path is a symlink into the
# generated tree, the same shape dnsmasq uses.
SAMBA_CONF_LINK_PATH = Path("/etc/samba/smb.conf")
SAMBA_GENERATED_NAME = "smb.conf"

# Every panel-created account joins this group; share directories are owned by
# it with setgid, so files members create stay writable to the others and
# permissions never fight. Debian ships this group; RHEL and Arch do not, and
# the provisioner creates it there. One name everywhere keeps the renderer
# pure and keeps an existing share working after an upgrade.
SAMBA_GROUP = "sambashare"

# Debian splits the daemons into smbd and nmbd and names the unit after the
# binary; RHEL and Arch ship one smb.service.
SAMBA_SERVICES = {
    "debian": "smbd",
    "rhel": "smb",
    "arch": "smb",
}

SAMBA_DEFAULT_SHARE_DIR = Path("/srv/share")
# Arrives through the package manager, which picks the machine's build.
SAMBA_SUPPORTED_ARCHITECTURES = ("*",)

SAMBA_PACKAGES = {
    "debian": ("samba",),
    "rhel": ("samba", "samba-client"),
    "arch": ("samba",),
}
