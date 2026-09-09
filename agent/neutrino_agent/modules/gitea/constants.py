"""Fixed values of the git server module."""

GITEA_BINARY_PATH = "/usr/local/bin/gitea"
GITEA_USER = "git"
GITEA_DIR = "/var/lib/gitea"
GITEA_ETC_DIR = "/etc/gitea"
GITEA_CONF_PATH = "/etc/gitea/app.ini"
GITEA_UNIT = "neutrino_gitea.service"
GITEA_UNIT_SOURCE_NAME = "neutrino_gitea.service"
GITEA_SYSTEMD_DIR = "/etc/systemd/system"

GITEA_DEFAULT_PORT = 3000

# Machine secrets app.ini needs: session signing, internal auth, JWTs. The
# hub generates them once per device and hands them down in the desired
# configuration.
GITEA_SECRET_NAMES = ("SECRET_KEY", "INTERNAL_TOKEN", "JWT_SECRET", "LFS_JWT_SECRET")

GITEA_COMMAND_ADMIN = "gitea_admin"
GITEA_COMMAND_PASSWORD = "gitea_password"
