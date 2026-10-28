"""Fixed values of the Ayakaleaf module."""

# The module's name on the wire. It names its record's directory and file.
AYAKALEAF_NAME = "ayakaleaf"

# The port the agent takes the forwarder's port from, the first free one up.
AYAKALEAF_BASE_PORT = 8900

# The module's three hub containers, as the hub composes them.
AYAKALEAF_APP_CONTAINER = "neutrino_ayakaleaf"
AYAKALEAF_MONGO_CONTAINER = "neutrino_ayakaleaf_mongo"
AYAKALEAF_REDIS_CONTAINER = "neutrino_ayakaleaf_redis"

# The volume a version change makes again, with the TeX Live of the new
# image.
AYAKALEAF_TEX_VOLUME = "neutrino_ayakaleaf_texlive"

# The first start's steps, in the order they run.
AYAKALEAF_STEP_REPLICA_SET = "replica_set"
AYAKALEAF_STEP_ADMIN = "admin"
AYAKALEAF_STEP_TEX = "tex"
AYAKALEAF_STEPS = (AYAKALEAF_STEP_REPLICA_SET, AYAKALEAF_STEP_ADMIN, AYAKALEAF_STEP_TEX)
AYAKALEAF_SETUP_FAILED = "ayakaleaf_setup_failed"

# The replica set step: mongosh in the mongo container, and how long it is
# tried again while mongod starts.
AYAKALEAF_MONGO_SHELL = ("mongosh", "--quiet", "--eval")
AYAKALEAF_REPLICA_SET_INITIATE = (
    'db.isMaster().primary || rs.initiate({_id: "overleaf", members: '
    '[{_id: 0, host: "neutrino_ayakaleaf_mongo:27017"}]})'
)
AYAKALEAF_REPLICA_SET_WAIT_S = 120

# The administrator the module makes, and the routes that make it.
AYAKALEAF_ADMIN_EMAIL = "admin@ayakaleaf.neutrino"
AYAKALEAF_LAUNCHPAD_PATH = "/launchpad"
AYAKALEAF_REGISTER_ADMIN_PATH = "/launchpad/register_admin"

# The TeX step: the collections ``tlmgr`` adds, the source set it reads from,
# the repository's path under each source, and how long one run may take.
AYAKALEAF_TEX_COLLECTIONS = (
    "collection-langchinese",
    "collection-xetex",
    "collection-latexrecommended",
)
# What ``tlmgr`` runs from one source, in order: its own update, then the
# collections. A ``tlmgr`` older than the repository refuses the install.
AYAKALEAF_TEX_VERBS = (
    ("update", "--self"),
    ("install", *AYAKALEAF_TEX_COLLECTIONS),
)
AYAKALEAF_TEX_SET = "ctan"
AYAKALEAF_TEX_REPOSITORY_PATH = "/systems/texlive/tlnet"
AYAKALEAF_TEX_TIMEOUT_S = 1800

# The app on its published port: the address, the page that answers 200
# with no login once the app has started, its login page and the project
# list a login redirects to.
AYAKALEAF_UPSTREAM_HOST = "127.0.0.1"
AYAKALEAF_STATUS_PATH = "/status"
AYAKALEAF_STATUS_TIMEOUT_S = 3.0
AYAKALEAF_LOGIN_PATH = "/login"
AYAKALEAF_PROJECT_PATH = "/project"
# The default name of the app's session cookie; the hub sends each device's
# own name.
AYAKALEAF_COOKIE = "overleaf.sid"

# The guest accounts: the routes the four steps of a new guest use, the
# route that deletes one, the invitation a guest accepts at each sign-in,
# and the code of a guest whose step failed.
AYAKALEAF_ADMIN_REGISTER_PATH = "/admin/register"
AYAKALEAF_ACTIVATE_PATH = "/user/activate"
AYAKALEAF_PASSWORD_SET_PATH = "/user/password/set"
AYAKALEAF_SETTINGS_PATH = "/user/settings"
AYAKALEAF_DELETE_USER_PATH = "/admin/user/{user_id}/delete"
AYAKALEAF_INVITE_PATH = "/project/{project_id}/invite/token/{token}"
AYAKALEAF_INVITE_TEMPLATE = "notification_project_invite"
AYAKALEAF_GUEST_FAILED = "ayakaleaf_guest_failed"
AYAKALEAF_GUEST_STEP_ADMIN_LOGIN = "admin_login"
AYAKALEAF_GUEST_STEP_REGISTER = "register"
AYAKALEAF_GUEST_STEP_PASSWORD = "password"  # scan: allow
AYAKALEAF_GUEST_STEP_NAME = "name"

# How long one podman call the hooks make may take, beside the TeX step.
AYAKALEAF_PODMAN_TIMEOUT_S = 120

# What the module keeps, root-only, in its record: the forwarder's port and
# secrets, the session cookie's name, the app's local name, the loopback
# port the app is published at, the version it last installed, the first
# start's steps done, whether its first start has ended, the guests made
# with their ``user_id``, each guest's failure, and whether it was stopped.
AYAKALEAF_RECORD_FIELDS = (
    "account",
    "port",
    "secret",
    "password",
    "cookie_name",
    "local_name",
    "upstream_port",
    "version",
    "steps",
    "is_ready",
    "guests",
    "guest_failures",
    "is_stopped",
)
# The fields whose change starts the forwarder again.
AYAKALEAF_FORWARDER_FIELDS = (
    "port",
    "secret",
    "password",
    "cookie_name",
    "local_name",
    "upstream_port",
)
# What the module waits on while its first start runs, and while a guest is
# owed and the app does not answer.
AYAKALEAF_PENDING = "ayakaleaf_first_start"
AYAKALEAF_GUESTS_PENDING = "ayakaleaf_guests"
