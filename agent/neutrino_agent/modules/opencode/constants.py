"""Fixed values of the OpenCode module."""

# The module's name on the wire, the runner a recipe names, its title, and
# the name a shell runs the program by.
OPENCODE_NAME = "opencode"
OPENCODE_RUNNER = "opencode"
OPENCODE_TITLE = "OpenCode"
OPENCODE_PROGRAM = "opencode"
# The variable naming the home folder OpenCode writes its own files in, by
# system, which its verify points into the module's directory.
OPENCODE_HOME_VARIABLES = {"windows": "USERPROFILE"}
OPENCODE_HOME_VARIABLE = "HOME"

# The places after PATH an account's own OpenCode is looked for, by system:
# the publisher's install script, the system's packages, Homebrew's, Scoop's,
# Chocolatey's and npm's.
OPENCODE_KNOWN_PLACES = {
    "linux": (
        "~/.opencode/bin/opencode",
        "/usr/local/bin/opencode",
        "/usr/bin/opencode",
    ),
    "darwin": (
        "~/.opencode/bin/opencode",
        "/opt/homebrew/bin/opencode",
        "/usr/local/bin/opencode",
    ),
    "windows": (
        "%USERPROFILE%\\scoop\\shims\\opencode.exe",
        "%ProgramData%\\chocolatey\\bin\\opencode.exe",
        "%APPDATA%\\npm\\opencode.cmd",
    ),
}

# The folder of the npm package that holds the program.
OPENCODE_BIN_DIR_NAME = "bin"
