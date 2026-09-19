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

# The verbs a ``command {module: gitea}`` names, beside ``validate``.
GITEA_COMMAND_ADMIN = "admin"
GITEA_COMMAND_PASSWORD = "password"
# How long the version and the administrator list stand before they are
# read again. Each read starts two gitea processes, and the agent reports
# every few seconds.
GITEA_SURVEY_TTL_S = 60.0
