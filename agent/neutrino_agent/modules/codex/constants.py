"""Fixed values of the Codex module."""

# The module's name on the wire, the runner a recipe names, its title, and
# the name a shell runs the program by.
CODEX_NAME = "codex"
CODEX_RUNNER = "codex"
CODEX_TITLE = "Codex"
CODEX_PROGRAM = "codex"

# The places after PATH an account's own Codex is looked for, by system:
# the publisher's install scripts, Homebrew's cask and npm.
CODEX_KNOWN_PLACES = {
    "linux": ("~/.local/bin/codex", "/usr/local/bin/codex"),
    "darwin": (
        "~/.local/bin/codex",
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ),
    "windows": (
        "%LOCALAPPDATA%\\Programs\\OpenAI\\Codex\\bin\\codex.exe",
        "%APPDATA%\\npm\\codex.cmd",
    ),
}

# The build target of the npm package for each system and architecture. The
# program is ``vendor/<target>/bin/codex`` under the module's copy.
CODEX_TARGETS = {
    ("linux", "amd64"): "x86_64-unknown-linux-musl",
    ("linux", "arm64"): "aarch64-unknown-linux-musl",
    ("darwin", "amd64"): "x86_64-apple-darwin",
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("windows", "amd64"): "x86_64-pc-windows-msvc",
    ("windows", "arm64"): "aarch64-pc-windows-msvc",
}
CODEX_VENDOR_DIR_NAME = "vendor"
CODEX_BIN_DIR_NAME = "bin"
