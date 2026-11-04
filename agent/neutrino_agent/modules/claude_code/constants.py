"""Fixed values of the Claude Code module."""

# The module's name on the wire, the runner a recipe names, its title, and
# the name a shell runs the program by.
CLAUDE_CODE_NAME = "claude_code"
CLAUDE_CODE_RUNNER = "claude_code"
CLAUDE_CODE_TITLE = "Claude Code"
CLAUDE_CODE_PROGRAM = "claude"

# The places after PATH an account's own Claude Code is looked for, by
# system: the native installer's, the system's packages, Homebrew's casks,
# WinGet's and npm's.
CLAUDE_CODE_KNOWN_PLACES = {
    "linux": ("~/.local/bin/claude", "/usr/local/bin/claude", "/usr/bin/claude"),
    "darwin": (
        "~/.local/bin/claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ),
    "windows": (
        "%USERPROFILE%\\.local\\bin\\claude.exe",
        "%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\claude.exe",
        "%APPDATA%\\npm\\claude.cmd",
    ),
}

# What the launcher sets: the copy's updater off.
CLAUDE_CODE_LAUNCHER_VARIABLES = (("DISABLE_UPDATES", "1"),)
