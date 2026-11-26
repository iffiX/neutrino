"""Fixed values of the ComfyUI module."""

# The module's name, its directory under the state root, and the data
# directory beside it, the service's account's.
COMFYUI_NAME = "comfyui"
COMFYUI_DATA_DIR_NAME = "comfyui_data"

# The artifacts the recipe names, and where each lands in the module's
# directory: the module's own Python, uv, ComfyUI's source, comfy-mcp's
# environment, the Visual C++ runtime beside the Python on Windows, and the
# venv's lock.
COMFYUI_ARTIFACT_PYTHON = "python"
COMFYUI_ARTIFACT_UV = "uv"
COMFYUI_ARTIFACT_SOURCE = "source"
COMFYUI_ARTIFACT_VC_RUNTIME = "vc_runtime"
COMFYUI_ARTIFACT_MCP = "mcp"
COMFYUI_ARTIFACT_VENV = "venv"
COMFYUI_PYTHON_DIR = "python"
COMFYUI_UV_DIR = "uv"
COMFYUI_SOURCE_DIR = "source"
COMFYUI_MCP_DIR = "mcp"
# The root-only folders of the module's directory: the parts of a lock
# written for uv, and the scripts and output files of the tasks on Windows.
COMFYUI_LOCKS_DIR = "locks"
COMFYUI_RUN_DIR = "run"
# The folder of the ``vc_runtime`` wheel whose files are copied beside the
# Python on Windows.
COMFYUI_VC_RUNTIME_MEMBER = "msvc_runtime-{version}.data/data"

# The data directory's parts: the venv, uv's cache, the service's temporary
# files and bytecode, and ``data/``, ComfyUI's base directory. The first four
# are the module's software, which an uninstall removes.
COMFYUI_VENV_DIR = "venv"
COMFYUI_UV_CACHE_DIR = "uv_cache"
COMFYUI_TMP_DIR = "tmp"
COMFYUI_PYCACHE_DIR = "pycache"
COMFYUI_BASE_DIR = "data"
COMFYUI_SOFTWARE_DIRS = (
    COMFYUI_VENV_DIR,
    COMFYUI_UV_CACHE_DIR,
    COMFYUI_TMP_DIR,
    COMFYUI_PYCACHE_DIR,
)
# The shared folders of ``data/``: those the default account writes, those
# it reads, and the service's own.
COMFYUI_WRITE_FOLDERS = ("models", "input", "output")
COMFYUI_READ_FOLDERS = ("user", "custom_nodes")
COMFYUI_SERVICE_FOLDERS = ("temp",)
COMFYUI_CUSTOM_NODES_DIR = "custom_nodes"
COMFYUI_REQUIREMENTS_NAME = "requirements.txt"

# ComfyUI's port and the forwarder's, each the first free one from its base
# up on ``127.0.0.1``.
COMFYUI_HOST = "127.0.0.1"
COMFYUI_BASE_PORT = 15000
COMFYUI_FORWARDER_BASE_PORT = 8188
# How the service starts ComfyUI, beside the port and the base directory,
# and the flag of the CPU build.
COMFYUI_MAIN_NAME = "main.py"
COMFYUI_SERVER_ARGUMENTS = ("--enable-manager",)
COMFYUI_CPU_ARGUMENT = "--cpu"

# ComfyUI's API: the read a start waits for and a report asks, the queue
# and the newest history entry idle unload reads, and the unload itself.
COMFYUI_STATS_PATH = "/system_stats"
COMFYUI_QUEUE_PATH = "/queue"
COMFYUI_HISTORY_PATH = "/history?max_items=1"
COMFYUI_FREE_PATH = "/free"
COMFYUI_FREE_BODY = b'{"unload_models": true, "free_memory": true}'
COMFYUI_PROBE_TIMEOUT_S = 1.0
COMFYUI_API_TIMEOUT_S = 10.0
COMFYUI_ANSWER_BYTES = 1 << 20
# How long a configure that runs the server waits for it, and how often it
# looks; how often idle unload reads the queue.
COMFYUI_START_WAIT_S = 300.0
COMFYUI_START_POLL_S = 1.0
COMFYUI_IDLE_POLL_S = 60.0

# The settings: the PyTorch builds, the one that runs on the CPU, the idle
# unload times as the hub spells them with their seconds, ``-1`` for never,
# and the default; the program modules comfy-mcp is named in.
COMFYUI_TORCH_BUILDS = ("nvidia", "amd", "intel", "cpu")
COMFYUI_TORCH_BUILD_CPU = "cpu"
COMFYUI_IDLE_UNLOAD_SECONDS = {"5m": 300, "30m": 1800, "1h": 3600, "4h": 14400}
COMFYUI_IDLE_UNLOAD_NEVER = "-1"
COMFYUI_IDLE_UNLOAD_DEFAULT = "30m"
COMFYUI_TOOLS = ("claude_code", "codex", "opencode")
COMFYUI_CODE_CONFIG_INVALID = "config_invalid"

# The module's record: its file's name and the fields it holds, each
# installed artifact's digest and the venv's lock among them.
COMFYUI_RECORD_NAME = "comfyui"
COMFYUI_RECORD_FIELDS = (
    "account",
    "port",
    "upstream_port",
    "secret",
    "cookie_name",
    "local_name",
    "default_account",
    "artifacts",
    "lock_digest",
    "index_url",
    "is_stopped",
)

# The forwarder's login cookie: the label its key is derived with, how long
# it lasts, and the token's query parameter it strips from a redirect.
COMFYUI_COOKIE_LABEL = b"neutrino comfyui cookie"
COMFYUI_LOGIN_LIFETIME_S = 7 * 24 * 3600
COMFYUI_FORWARDER_FIELDS = ("port", "upstream_port", "secret", "cookie_name")

# How long one uv command runs at most, and how long one step a service's
# account runs.
COMFYUI_UV_TIMEOUT_S = 3600
COMFYUI_ACCOUNT_STEP_TIMEOUT_S = 120
# How much of the server's output a failed start names.
COMFYUI_DETAIL_CHARS = 500

# Linux: the system account, its mark, its shells, the groups that reach a
# GPU, the unit and where it is written, and the umask the server runs with.
COMFYUI_LINUX_ACCOUNT = "neutrino_comfyui"
COMFYUI_LINUX_ACCOUNT_COMMENT = "neutrino comfyui"
COMFYUI_LINUX_SHELLS = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false")
COMFYUI_LINUX_GPU_GROUPS = ("render", "video")
COMFYUI_LINUX_UNIT = "neutrino_comfyui.service"
COMFYUI_LINUX_SYSTEMD_DIR = "/etc/systemd/system"
COMFYUI_LINUX_UMASK = "0027"
COMFYUI_POSIX_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
COMFYUI_POSIX_ENV = "/usr/bin/env"

# macOS: the hidden account, its full name and shell, the LaunchDaemon and
# its umask, and where launchd writes its output.
COMFYUI_DARWIN_ACCOUNT = "neutrino_comfyui"
COMFYUI_DARWIN_ACCOUNT_FULL_NAME = "Neutrino ComfyUI"
COMFYUI_DARWIN_SHELL = "/usr/bin/false"
COMFYUI_DARWIN_LABEL = "com.neutrino.comfyui"
COMFYUI_DARWIN_LAUNCHD_DIR = "/Library/LaunchDaemons"
COMFYUI_DARWIN_UMASK = 23
COMFYUI_DARWIN_OUTPUT_PATH = "/Library/Logs/Neutrino/agent/comfyui.log"
COMFYUI_DARWIN_UNLOAD_TIMEOUT_S = 30
COMFYUI_DARWIN_UNLOAD_POLL_S = 0.5

# Windows: the account the service and uv run as, by its SID, the scheduled task, its
# description's marker, its script, the one-shot task uv runs in and how
# often it is read, the server's log, and how a stop and an uninstall wait.
COMFYUI_WINDOWS_ACCOUNT = "S-1-5-19"
COMFYUI_WINDOWS_SERVICE_SID = "*S-1-5-19"
# The SIDs whose own entries stay on the shared folders beside the default
# account's: SYSTEM, the administrators and LOCAL SERVICE.
COMFYUI_WINDOWS_KEPT_SIDS = ("S-1-5-18", "S-1-5-32-544", "S-1-5-19")
COMFYUI_WINDOWS_TASK = "neutrino_comfyui"
COMFYUI_WINDOWS_TASK_MARKER = "neutrino:"
COMFYUI_WINDOWS_SCRIPT_NAME = "serve.cmd"
COMFYUI_WINDOWS_STEP_TASK = "neutrino_comfyui_step"
COMFYUI_WINDOWS_STEP_SCRIPT_NAME = "step.cmd"
COMFYUI_WINDOWS_STEP_OUTPUT_NAME = "step.log"
COMFYUI_WINDOWS_STEP_POLL_S = 2.0
COMFYUI_WINDOWS_LOG_NAME = "comfyui.log"
COMFYUI_WINDOWS_STOP_TRIES = 30
COMFYUI_WINDOWS_STOP_RETRY_S = 0.5
COMFYUI_WINDOWS_REMOVE_TRIES = 30
COMFYUI_WINDOWS_REMOVE_RETRY_S = 1.0

# comfy-mcp: its programs in its environment, the server's name in every
# tool, the variables it runs with, and the workspace in the default
# account's own Neutrino tree with what links into it.
COMFYUI_MCP_SERVER = "comfyui"
COMFYUI_MCP_PROGRAM = "comfy-mcp"
COMFYUI_MCP_COMFY = "comfy"
COMFYUI_MCP_FIXED_ENVIRONMENT = {"DO_NOT_TRACK": "1"}
COMFYUI_MCP_GIT_ENVIRONMENT = {
    "GIT_PYTHON_REFRESH": "quiet",
    "GIT_PYTHON_GIT_EXECUTABLE": "/nonexistent/neutrino/git",
}
COMFYUI_WORKSPACE_DIR = "workspace"
COMFYUI_WORKSPACE_SOURCE_FILES = ("main.py", "nodes.py")
COMFYUI_WORKSPACE_SOURCE_DIRS = ("comfy", "comfy_extras", "comfy_api")
COMFYUI_WORKSPACE_SHARED_DIRS = COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS
# The module's folder in an account's own Neutrino tree, below its home.
COMFYUI_ACCOUNT_TREE_PARTS = {
    "linux": (".local", "share", "neutrino", "agent", "comfyui"),
    "darwin": ("Library", "Application Support", "Neutrino", "agent", "comfyui"),
    "windows": ("AppData", "Local", "Neutrino", "agent", "comfyui"),
}
# Each tool's file below the account's home.
COMFYUI_TOOL_FILES = {
    "claude_code": (".claude.json",),
    "codex": (".codex", "config.toml"),
    "opencode": (".config", "opencode", "opencode.json"),
}
