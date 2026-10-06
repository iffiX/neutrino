"""cc-switch as a small scripted store, and an account it runs as.

The store answers the way cc-switch 5.10.4 does to the commands the
switcher makes, and keeps every call in order. The account is a home of
files in memory: whatever the session reads, writes or removes there is a
call recorded too, so a test can say what was done and as whom. As the
real one does, the store writes a tool's files on ``use`` only into a tool
directory that is there, and switching to another provider writes that
provider's settings laid out its own way.
"""

import json

from neutrino_agent.ai_tools.constants import AI_TOOLS_APPS, AI_TOOLS_PROVIDER_ID
from neutrino_agent.exceptions import ToolSwitchError

# The file a provider's settings are written to for each tool.
LIVE_FILES = {
    "claude": (".claude", "settings.json"),
    "codex": (".codex", "config.toml"),
    "gemini": (".gemini", ".env"),
}


def has_dir(files: dict, dirs: set, path: str) -> bool:
    """Whether a directory is in a home of files in memory."""
    return path in dirs or any(
        name.startswith(path + "/") or name.startswith(path + "\\") for name in files
    )


def flag_values(arguments) -> dict:
    """The ``--flag=value`` pairs of a provider add, as a dict."""
    return {
        flag: value
        for flag, value in (
            argument.split("=", 1) for argument in arguments if "=" in argument
        )
    }


class FakeCcSwitch:
    """cc-switch, scripted: a store per tool, and every call made."""

    HEADER = "Common Config Snippet\n=====\nApp: {app}\n"

    def __init__(self, *, current="default", extracted=""):
        self.calls: list = []
        self.current = {app: current for app in AI_TOOLS_APPS}
        self.snippet = {app: "" for app in AI_TOOLS_APPS}
        self.providers = {app: {current} if current else set() for app in AI_TOOLS_APPS}
        self.extracted = extracted
        self.added: dict = {}
        self.refusals: dict = {}
        self.is_delete_kept = False

    def answer(self, session, arguments, app) -> tuple:
        """``(returncode, stdout, stderr)`` for one call, as the account."""
        key = tuple(arguments)
        self.calls.append((session.account, app, key))
        for prefix, words in self.refusals.items():
            if key[: len(prefix)] == prefix:
                return 1, "", words
        if key[:2] == ("provider", "list"):
            rows = ["│   ┆ ID ┆ Name ┆ API URL │"]
            for identifier in sorted(self.providers[app]):
                mark = "✓" if identifier == self.current[app] else " "
                rows.append(f"│ {mark} ┆ {identifier} ┆ {identifier} ┆ N/A │")
            return 0, "\n".join(rows) + "\n", ""
        if key[:2] == ("provider", "current"):
            if self.current[app]:
                return 0, f"Current Provider\n  ID:       {self.current[app]}\n", ""
            return 0, "Error: Current provider '' not found\n", ""
        if key[:2] == ("provider", "add"):
            self.providers[app].add(key[key.index("--id") + 1])
            self.added[app] = key
            return 0, "added", ""
        if key[:1] == ("use",):
            self.current[app] = key[1]
            folder = {"claude": ".claude", "codex": ".codex", "gemini": ".gemini"}[app]
            if not session.has_dir(session.path(folder)):
                return 0, "Live sync skipped: client not initialized", ""
            given = flag_values(self.added.get(app, ()))
            if key[1] != AI_TOOLS_PROVIDER_ID:
                live = session.path(*LIVE_FILES[app])
                if live in session.files:
                    session.files[live] = session.files[live].replace(" ", "")
                return 0, "", ""
            if app == "claude":
                env = {
                    "ANTHROPIC_BASE_URL": given["--base-url"],
                    "ANTHROPIC_AUTH_TOKEN": given["--api-key"],
                }
                if "--model" in given:
                    env["ANTHROPIC_MODEL"] = given["--model"]
                session.files[session.path(".claude", "settings.json")] = json.dumps(
                    {"env": env}
                )
            elif app == "codex":
                session.files[session.path(".codex", "config.toml")] = (
                    f'model_provider = "custom"\nbase_url = "{given["--base-url"]}"\n'
                )
                session.files[session.path(".codex", "auth.json")] = json.dumps(
                    {"OPENAI_API_KEY": given["--api-key"]}
                )
            else:
                session.files[session.path(".gemini", ".env")] = (
                    f"GEMINI_API_KEY={given['--api-key']}\n"
                    f"GOOGLE_GEMINI_BASE_URL={given['--base-url']}"
                )
                session.files[session.path(".gemini", "settings.json")] = "{}"
            return 0, "", ""
        if key[:2] == ("provider", "delete"):
            if not self.is_delete_kept:
                self.providers[app].discard(key[2])
            return 0, "Delete provider 'neutrino'? (y/N) y\r\nDeleted\r\n", ""
        if key[:3] == ("config", "common", "show"):
            return 0, self.HEADER.format(app=app) + self.snippet[app], ""
        if key[:3] == ("config", "common", "extract"):
            return 0, self.extracted, ""
        if key[:3] == ("config", "common", "set"):
            self.snippet[app] = session.files[key[4]]
            return 0, "", ""
        return 0, "", ""

    def made(self, app) -> list:
        """The verbs called for one tool, in order."""
        return [
            " ".join(key[:3] if key[:1] == ("config",) else key[:2])
            for _account, made_app, key in self.calls
            if made_app == app
        ]


class FakeSession:
    """One account as the switcher reaches it: a home in memory and the store."""

    def __init__(
        self, cc_switch, *, account="ann", home="/home/ann", files=None, dirs=()
    ):
        self.account = account
        self.home = home
        self.cc_switch = cc_switch
        self.files: dict = dict(files or {})
        self.dirs: set = {self.path(name) for name in dirs}
        self.file_calls: list = []
        self.answered: list = []

    def path(self, *parts):
        return "/".join([self.home, *parts])

    def payload_path(self):
        return self.path(".local", "share", "neutrino", "agent", "ai_tools", "payload")

    def remove_payload(self):
        self.remove(self.payload_path())

    def failure(self, detail):
        return ToolSwitchError(
            "switch_failed", {"account": self.account, "detail": detail[:300]}
        )

    def cc(self, arguments, app, *, is_checked=True):
        import subprocess

        code, out, err = self.cc_switch.answer(self, arguments, app)
        if is_checked and code != 0:
            raise subprocess.CalledProcessError(
                code, ["cc-switch"], output=out, stderr=err
            )
        return out

    def cc_answering(self, arguments, app, *, prompt, answer):
        self.answered.append((tuple(arguments), prompt, answer))
        return self.cc_switch.answer(self, arguments, app)[1]

    def read_text(self, path):
        self.file_calls.append(("read", path))
        return self.files.get(path, "")

    def is_file(self, path):
        self.file_calls.append(("is_file", path))
        return path in self.files

    def write_text(self, path, text):
        self.file_calls.append(("write", path))
        self.files[path] = text

    def remove(self, path):
        self.file_calls.append(("remove", path))
        self.files.pop(path, None)

    def has_dir(self, path):
        return has_dir(self.files, self.dirs, path)

    def is_dir(self, path):
        self.file_calls.append(("is_dir", path))
        return self.has_dir(path)

    def make_dir(self, path):
        self.file_calls.append(("make_dir", path))
        self.dirs.add(path)

    def remove_empty_dir(self, path):
        self.file_calls.append(("remove_empty_dir", path))
        if not any(name.startswith(path + "/") for name in self.files):
            self.dirs.discard(path)
