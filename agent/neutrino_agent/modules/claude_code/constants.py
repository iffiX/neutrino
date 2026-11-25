"""Fixed values of the Claude Code module."""

# The module's name on the wire, the runner a recipe names, its title, and
# the name a shell runs the program by.
CLAUDE_CODE_NAME = "claude_code"
CLAUDE_CODE_RUNNER = "claude_code"
CLAUDE_CODE_TITLE = "Claude Code"
CLAUDE_CODE_PROGRAM = "claude"

# What the launcher sets: the copy's updater off.
CLAUDE_CODE_LAUNCHER_VARIABLES = (("DISABLE_UPDATES", "1"),)
