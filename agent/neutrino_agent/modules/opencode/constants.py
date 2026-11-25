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

# The folder of the npm package that holds the program.
OPENCODE_BIN_DIR_NAME = "bin"
