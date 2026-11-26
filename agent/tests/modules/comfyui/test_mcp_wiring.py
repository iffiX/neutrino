"""comfy-mcp for the default account: the workspace and each tool's entry, every file touched as the account.

What these pin, with the account's commands faked: the workspace made as
the account with its links to the sealed source and to the shared folders;
on Windows junctions for the folders and copies of ``main.py`` and
``nodes.py``, written again when the source changes; each tool the state
names getting the ``comfyui`` entry with ComfyUI's port, written again when
it is missing or the port changed and left when it is right; a tool the
state no longer names losing the module's entry; the uninstall taking each
entry and the workspace away; every read and write made as the account.
"""

import json
import os

from neutrino_agent.modules.comfyui.mcp_wiring import ComfyuiMcpWiring


class Platform:
    def __init__(self, home, os_name="linux"):
        self.home = home
        self.os_name = os_name

    def account_home(self, account):
        assert account == "anna"
        return self.home


class Files:
    """The account's places, kept in memory, each act recorded as the account's."""

    def __init__(self, store, acts, **kwargs):
        self.store = store
        self.acts = acts
        self.account = kwargs["account"]

    def read(self, path):
        self.acts.append((self.account, "read", path))
        held = self.store.get(path)
        return held if isinstance(held, bytes) else None

    def write(self, path, data, mode=0o600):
        self.acts.append((self.account, "write", path))
        self.store[path] = data

    def make_dir(self, path, umask=0o077):
        self.acts.append((self.account, "make_dir", path))
        self.store[path] = "dir"
        return True

    def link(self, target, path):
        self.acts.append((self.account, "link", path))
        self.store[path] = ("link", target)
        return True

    def remove_tree(self, path):
        self.acts.append((self.account, "remove_tree", path))
        for key in [key for key in self.store if key.startswith(path)]:
            del self.store[key]


def wiring(tmp_path, os_name="linux"):
    store, acts = {}, []
    source = tmp_path / "comfyui" / "source"
    os.makedirs(source)
    (source / "main.py").write_text("main\n")
    (source / "nodes.py").write_text("nodes\n")
    made = ComfyuiMcpWiring(
        platform=Platform("/home/anna", os_name),
        module_dir=str(tmp_path / "comfyui"),
        base_dir="/state/comfyui_data/data",
        log=lambda line: None,
        files_factory=lambda **kwargs: Files(store, acts, **kwargs),
        is_git_missing=lambda: False,
    )
    return made, store, acts


def test_the_workspace_links_to_the_source_and_the_shared_folders(tmp_path):
    made, store, acts = wiring(tmp_path)
    made.apply(account="anna", password="", tools=[], port=15000)
    workspace = "/home/anna/.local/share/neutrino/agent/comfyui/workspace"
    assert store[workspace] == "dir"
    for name in ("comfy", "comfy_extras", "comfy_api", "main.py", "nodes.py"):
        assert store[f"{workspace}/{name}"] == (
            "link",
            str(tmp_path / "comfyui" / "source" / name),
        )
    for name in ("models", "input", "output", "user", "custom_nodes"):
        assert store[f"{workspace}/{name}"] == (
            "link",
            f"/state/comfyui_data/data/{name}",
        )
    assert {account for account, _act, _path in acts} == {"anna"}


def test_windows_copies_the_two_files_again_when_the_source_changes(tmp_path):
    made, store, _acts = wiring(tmp_path, "windows")
    made.apply(account="anna", password="pw", tools=[], port=15000)
    copies = [key for key, value in store.items() if isinstance(value, bytes)]
    assert sorted(os.path.basename(path.replace("\\", "/")) for path in copies) == [
        "main.py",
        "nodes.py",
    ]
    (tmp_path / "comfyui" / "source" / "main.py").write_text("new\n")
    made.apply(account="anna", password="pw", tools=[], port=15000)
    main = [path for path in copies if path.endswith("main.py")][0]
    assert store[main] == b"new\n"


def test_each_named_tool_gets_the_entry_with_the_port_and_a_right_entry_stays(tmp_path):
    made, store, acts = wiring(tmp_path)
    store["/home/anna/.claude.json"] = json.dumps({"numStartups": 1}).encode()
    written = made.apply(
        account="anna", password="", tools=["claude_code", "opencode"], port=15000
    )
    assert written == ["claude_code", "opencode"]
    claude = json.loads(store["/home/anna/.claude.json"])
    assert claude["numStartups"] == 1
    entry = claude["mcpServers"]["comfyui"]
    assert entry["command"] == str(tmp_path / "comfyui" / "mcp" / "bin" / "comfy-mcp")
    assert entry["env"]["COMFY_LOCAL_URL"] == "http://127.0.0.1:15000"
    assert "/home/anna/.codex/config.toml" not in store
    acts.clear()
    assert (
        made.apply(
            account="anna", password="", tools=["claude_code", "opencode"], port=15000
        )
        == []
    )
    assert not [act for act in acts if act[1] == "write" and act[2].endswith(".json")]
    assert made.apply(
        account="anna", password="", tools=["claude_code", "opencode"], port=15001
    ) == [
        "claude_code",
        "opencode",
    ]
    assert (
        json.loads(store["/home/anna/.claude.json"])["mcpServers"]["comfyui"]["env"][
            "COMFY_LOCAL_URL"
        ]
        == "http://127.0.0.1:15001"
    )


def test_a_tool_no_longer_named_loses_the_modules_entry_alone(tmp_path):
    made, store, _acts = wiring(tmp_path)
    made.apply(account="anna", password="", tools=["opencode"], port=15000)
    document = json.loads(store["/home/anna/.config/opencode/opencode.json"])
    document["mcp"]["mine"] = {"type": "local", "command": ["x"]}
    store["/home/anna/.config/opencode/opencode.json"] = json.dumps(document).encode()
    assert made.apply(account="anna", password="", tools=[], port=15000) == ["opencode"]
    assert json.loads(store["/home/anna/.config/opencode/opencode.json"]) == {
        "mcp": {"mine": {"type": "local", "command": ["x"]}}
    }


def test_the_uninstall_takes_each_entry_and_the_workspace(tmp_path):
    made, store, _acts = wiring(tmp_path)
    made.apply(account="anna", password="", tools=["claude_code", "codex"], port=15000)
    made.remove(account="anna", password="")
    assert json.loads(store["/home/anna/.claude.json"]) == {"mcpServers": {}}
    assert store["/home/anna/.codex/config.toml"] == b""
    assert not [key for key in store if "/comfyui/workspace" in key]
