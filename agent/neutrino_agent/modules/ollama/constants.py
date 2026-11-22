"""Fixed values of the Ollama module."""

# The module's name, its artifact's directory under the module's directory,
# and the data directory beside the module's under the state root.
OLLAMA_NAME = "ollama"
OLLAMA_PROGRAM_DIR_NAME = "ollama"
OLLAMA_DATA_DIR_NAME = "ollama_data"
# The folder of the data directory the models live in, and Ollama's own
# folder there, which holds its key.
OLLAMA_MODELS_DIR_NAME = "models"
OLLAMA_OWN_DIR_NAME = ".ollama"

# The one address and port the server listens on, and the environment every
# system's service starts it with beside these.
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_ENVIRONMENT = {"OLLAMA_NO_CLOUD": "1"}
# What the server is started with.
OLLAMA_SERVE_ARGUMENTS = ("serve",)
# The server's version document, how long a read of it waits, and the words
# ``ollama --version`` names its version after.
OLLAMA_VERSION_PATH = "/api/version"
OLLAMA_PROBE_TIMEOUT_S = 1.0
# How long a version the server answered stands before a report asks again.
# Each ask is a line in the server's log, and the agent reports every few
# seconds.
OLLAMA_VERSION_TTL_S = 600.0
# How long the program's ``--version`` may take.
OLLAMA_VERSION_TIMEOUT_S = 30
OLLAMA_VERSION_MARKERS = ("ollama version is ", "client version is ")

# How long a configure that runs the server waits for it to answer, and how
# often it looks.
OLLAMA_START_WAIT_S = 60.0
OLLAMA_START_POLL_S = 0.5

# What a person's own Ollama is, as ``details.found`` names it: the unit of
# Linux.
OLLAMA_FOUND_UNIT = "unit"
# The publisher's app taken over on Windows and macOS: the folder under the
# module's directory its start at login is kept aside in, and the record of
# each account taken over in it.
OLLAMA_KEPT_DIR_NAME = "kept"
OLLAMA_KEPT_RECORD_NAME = "apps.json"
# The module's record: its file's name and the fields it holds.
OLLAMA_RECORD_NAME = "ollama"
OLLAMA_RECORD_FIELDS = ("account", "found_unit")

# The refusal of a configuration outside the settings.
OLLAMA_CODE_CONFIG_INVALID = "config_invalid"

# The settings: how long a model a request loaded stays in memory, as
# ``OLLAMA_KEEP_ALIVE`` spells it, ``-1`` for never, and its default.
OLLAMA_KEEP_ALIVE_CHOICES = ("5m", "30m", "1h", "4h", "-1")
OLLAMA_KEEP_ALIVE_DEFAULT = "30m"
OLLAMA_KEEP_ALIVE_VARIABLE = "OLLAMA_KEEP_ALIVE"
# The most tokens a loaded model holds: its least and most value, its
# default and its variable.
OLLAMA_CONTEXT_LENGTH_MIN = 4096
OLLAMA_CONTEXT_LENGTH_MAX = 262144
OLLAMA_CONTEXT_LENGTH_DEFAULT = 65536
OLLAMA_CONTEXT_LENGTH_VARIABLE = "OLLAMA_CONTEXT_LENGTH"
# The GPU variables, each naming the cards of its group to use: the vendors
# a group takes, or the vendors it leaves out. CUDA counts its cards in PCI
# bus order beside its variable, the order ``nvidia-smi`` lists them in.
OLLAMA_GPU_NVIDIA = "nvidia"
OLLAMA_GPU_AMD = "amd"
OLLAMA_GPU_APPLE = "apple"
OLLAMA_GPU_CUDA_VARIABLE = "CUDA_VISIBLE_DEVICES"
OLLAMA_GPU_ROCM_VARIABLE = "ROCR_VISIBLE_DEVICES"
OLLAMA_GPU_VULKAN_VARIABLE = "GGML_VK_VISIBLE_DEVICES"
OLLAMA_GPU_CUDA_ORDER = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
OLLAMA_GPU_NONE = "-1"
# The system whose server reaches its GPU through Metal and takes no GPU
# variable.
OLLAMA_GPU_FREE_OS = "darwin"

# Linux: the system account, its mark, its shell, the groups that reach a
# GPU, the unit, where it is written, and a person's unit with the places
# its file is found in.
OLLAMA_LINUX_ACCOUNT = "neutrino_ollama"
OLLAMA_LINUX_ACCOUNT_COMMENT = "neutrino ollama"
OLLAMA_LINUX_SHELLS = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false")
OLLAMA_LINUX_GPU_GROUPS = ("render", "video")
OLLAMA_LINUX_UNIT = "neutrino_ollama.service"
OLLAMA_LINUX_SYSTEMD_DIR = "/etc/systemd/system"
OLLAMA_LINUX_PROGRAM_PARTS = ("bin", "ollama")
OLLAMA_PERSON_UNIT = "ollama.service"
# The drop-in that gives a person's unit the settings, under the systemd
# folder: the unit's ``.d`` folder and the module's own file in it.
OLLAMA_PERSON_DROP_IN_PARTS = ("ollama.service.d", "neutrino.conf")
OLLAMA_PERSON_UNIT_PATHS = (
    "/etc/systemd/system/ollama.service",
    "/usr/lib/systemd/system/ollama.service",
    "/lib/systemd/system/ollama.service",
)

# macOS: the hidden account, its full name and shell, the LaunchDaemon, where
# launchd writes its output, the publisher's app, and how long a booted-out
# job is waited for.
OLLAMA_DARWIN_ACCOUNT = "neutrino_ollama"
OLLAMA_DARWIN_ACCOUNT_FULL_NAME = "Neutrino Ollama"
OLLAMA_DARWIN_SHELL = "/usr/bin/false"
OLLAMA_DARWIN_LABEL = "com.neutrino.ollama"
OLLAMA_DARWIN_LAUNCHD_DIR = "/Library/LaunchDaemons"
OLLAMA_DARWIN_OUTPUT_PATH = "/Library/Logs/Neutrino/agent/ollama.log"
OLLAMA_DARWIN_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
OLLAMA_DARWIN_APP_PATHS = ("/Applications/Ollama.app",)
# The login job the app registers with SMAppService in each account's gui
# domain, and the least uid of a person's account.
OLLAMA_DARWIN_APP_JOB = "com.ollama.ollama"
OLLAMA_DARWIN_FIRST_UID = 501
OLLAMA_DARWIN_UNLOAD_TIMEOUT_S = 30
OLLAMA_DARWIN_UNLOAD_POLL_S = 0.5
# The parts of the data directory a handover gives on macOS, whose data
# directory is also the account's home.
OLLAMA_DARWIN_OWN_PARTS = (OLLAMA_MODELS_DIR_NAME, OLLAMA_OWN_DIR_NAME)

# Windows: the scheduled task, its description's marker, the script it runs
# under the module's directory, the log in the data directory, the program,
# and where the publisher's app is found in a profile.
OLLAMA_WINDOWS_TASK = "neutrino_ollama"
OLLAMA_WINDOWS_TASK_MARKER = "neutrino:"
OLLAMA_WINDOWS_SCRIPT_PARTS = ("run", "serve.cmd")
OLLAMA_WINDOWS_LOG_NAME = "ollama.log"
OLLAMA_WINDOWS_PROGRAM_NAME = "ollama.exe"
OLLAMA_WINDOWS_APP_DIR_PARTS = ("AppData", "Local", "Programs", "Ollama")
OLLAMA_WINDOWS_APP_PROGRAM_NAME = "ollama app.exe"
# The app's start at login: the shortcut it copies into the profile's
# Startup folder at its first start.
OLLAMA_WINDOWS_STARTUP_PARTS = (
    "AppData",
    "Roaming",
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "Startup",
)
OLLAMA_WINDOWS_STARTUP_NAME = "Ollama.lnk"
# The task that opens the app again once as an account, interactive only.
OLLAMA_WINDOWS_OPEN_TASK = "neutrino_ollama_app"
# How many times, and how often, a stop waits for the program's processes to
# end, and an uninstall deletes the module's directory.
OLLAMA_WINDOWS_STOP_TRIES = 30
OLLAMA_WINDOWS_STOP_RETRY_S = 0.5
OLLAMA_WINDOWS_REMOVE_TRIES = 30
OLLAMA_WINDOWS_REMOVE_RETRY_S = 1.0
