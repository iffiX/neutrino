"""comfy-mcp for the default account: its workspace and the entry of each of its tools, each written as the account.

The workspace is ``comfyui/workspace/`` in the account's own Neutrino tree.
``main.py``, ``nodes.py``, ``comfy/``, ``comfy_extras/`` and ``comfy_api/``
in it link to the sealed source, and ``models/``, ``input/``, ``output/``,
``user/`` and ``custom_nodes/`` to the shared folders. On Windows the
folders are junctions and the two files copies, written again when the
source changes. Each tool the state names gets the ``comfyui`` entry,
written again where it is missing or differs; a tool the state no longer
names loses the entry whose program is the module's.

Not pure: touches the account's files as the account.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_ACCOUNT_TREE_PARTS,
    COMFYUI_HOST,
    COMFYUI_MCP_COMFY,
    COMFYUI_MCP_DIR,
    COMFYUI_MCP_FIXED_ENVIRONMENT,
    COMFYUI_MCP_GIT_ENVIRONMENT,
    COMFYUI_MCP_PROGRAM,
    COMFYUI_SOURCE_DIR,
    COMFYUI_TOOL_FILES,
    COMFYUI_TOOLS,
    COMFYUI_WORKSPACE_DIR,
    COMFYUI_WORKSPACE_SHARED_DIRS,
    COMFYUI_WORKSPACE_SOURCE_DIRS,
    COMFYUI_WORKSPACE_SOURCE_FILES,
)
from neutrino_agent.modules.comfyui.mcp_entries import (
    entry_of,
    with_entry,
    without_entry,
)
from neutrino_agent.modules.gitea.constants import GITEA_DARWIN_GIT_PATHS
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.package import joiner


def mcp_program(mcp_dir: str, name: str, os_name: str) -> str:
    """One program of comfy-mcp's environment. Pure.

    Args:
        mcp_dir: The environment.
        name: ``comfy-mcp`` or ``comfy``.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        ``Scripts\\<name>.exe`` on Windows, ``bin/<name>`` elsewhere.
    """
    join = joiner(os_name)
    if os_name == "windows":
        return join(mcp_dir, "Scripts", name + ".exe")
    return join(mcp_dir, "bin", name)


def mcp_environment(
    *, mcp_dir: str, port: int, workspace: str, os_name: str, is_git_missing: bool
) -> dict:
    """The variables comfy-mcp runs with. Pure.

    Args:
        mcp_dir: comfy-mcp's environment.
        port: ComfyUI's own port.
        workspace: The account's workspace.
        os_name: ``linux``, ``darwin`` or ``windows``.
        is_git_missing: Whether a Mac has no usable ``git``.

    Returns:
        ``COMFY_BIN``, ``COMFY_LOCAL_URL``, ``COMFY_PROJECT`` and
        ``DO_NOT_TRACK``, and GitPython's two variables on a Mac with no
        ``git``.
    """
    environment = {
        "COMFY_BIN": mcp_program(mcp_dir, COMFYUI_MCP_COMFY, os_name),
        "COMFY_LOCAL_URL": f"http://{COMFYUI_HOST}:{int(port)}",
        "COMFY_PROJECT": workspace,
        **COMFYUI_MCP_FIXED_ENVIRONMENT,
    }
    if is_git_missing:
        environment.update(COMFYUI_MCP_GIT_ENVIRONMENT)
    return environment


def is_mac_git_missing() -> bool:
    """Whether this Mac has no usable ``git`` where Gitea reads one."""
    return not any(os.access(path, os.X_OK) for path in GITEA_DARWIN_GIT_PATHS)


class ComfyuiMcpWiring:
    """The default account's workspace and tool entries for comfy-mcp."""

    def __init__(
        self,
        *,
        platform,
        module_dir: str,
        base_dir: str,
        log=print,
        files_factory=AccountFiles,
        is_git_missing=is_mac_git_missing,
    ):
        """
        Args:
            platform: The machine's platform, which reaches an account's
                home and acts as it.
            module_dir: The module's directory, whose ``source`` and ``mcp``
                the workspace and the entries name.
            base_dir: ``data/`` in the data directory, the shared folders.
            log: Called with each progress line.
            files_factory: Makes the :class:`AccountFiles` of an account.
            is_git_missing: Called on a Mac; whether it has no usable
                ``git``.
        """
        self._platform = platform
        self._os_name = platform.os_name
        self._join = joiner(self._os_name)
        self._module_dir = module_dir
        self._source_dir = self._join(module_dir, COMFYUI_SOURCE_DIR)
        self._mcp_dir = self._join(module_dir, COMFYUI_MCP_DIR)
        self._base_dir = base_dir
        self._log = log
        self._files_factory = files_factory
        self._is_git_missing = is_git_missing

    @property
    def program(self) -> str:
        """comfy-mcp's program, which each tool's entry names."""
        return mcp_program(self._mcp_dir, COMFYUI_MCP_PROGRAM, self._os_name)

    def apply(self, *, account: str, password: str, tools: list, port: int) -> list:
        """Make the account's workspace and write each tool's entry.

        Args:
            account: The default account.
            password: Its login on Windows.
            tools: The program modules whose tool names comfy-mcp.
            port: ComfyUI's own port.

        Returns:
            The tools whose file was written.

        Raises:
            OSError: When the workspace cannot be made.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        home = self._platform.account_home(account)
        files = self._files_factory(
            platform=self._platform, account=account, password=password
        )
        workspace = self._workspace(home)
        self._make_workspace(files, workspace)
        environment = mcp_environment(
            mcp_dir=self._mcp_dir,
            port=port,
            workspace=workspace,
            os_name=self._os_name,
            is_git_missing=self._os_name == "darwin" and self._is_git_missing(),
        )
        written = []
        for tool in COMFYUI_TOOLS:
            path = self._join(home, *COMFYUI_TOOL_FILES[tool])
            if tool in tools:
                entry = entry_of(tool, program=self.program, environment=environment)
                if self._edit(files, tool, path, with_entry, entry):
                    written.append(tool)
            elif self._edit(files, tool, path, self._without_ours):
                written.append(tool)
        return written

    def remove(self, *, account: str, password: str) -> None:
        """Take the module's entry out of each tool's file, and the account's workspace away.

        Args:
            account: The default account.
            password: Its login on Windows.
        """
        try:
            home = self._platform.account_home(account)
        except (KeyError, OSError) as error:
            self._log(f"comfyui: no home of {account} to clean: {error}")
            return
        files = self._files_factory(
            platform=self._platform, account=account, password=password
        )
        for tool in COMFYUI_TOOLS:
            path = self._join(home, *COMFYUI_TOOL_FILES[tool])
            self._edit(files, tool, path, self._without_ours)
        tree = self._join(home, *self._tree_parts())
        try:
            files.remove_tree(tree)
        except (OSError, ModuleApplyError) as error:
            self._log(f"comfyui: the workspace of {account} stays: {error}")

    def _tree_parts(self) -> tuple:
        return COMFYUI_ACCOUNT_TREE_PARTS[self._os_name]

    def _workspace(self, home: str) -> str:
        return self._join(home, *self._tree_parts(), COMFYUI_WORKSPACE_DIR)

    def _without_ours(self, tool: str, text: str):
        """A tool's file with the module's own entry taken out."""
        return without_entry(tool, text, program=self.program)

    def _edit(self, files, tool: str, path: str, edit, *arguments) -> bool:
        """Read one tool's file as the account, edit it, and write it back when it changed.

        Returns:
            Whether the file was written; a file the edit cannot read is
            left as it is with a line in the log.
        """
        try:
            held = files.read(path)
        except (OSError, ModuleApplyError) as error:
            self._log(f"comfyui: cannot read {path}: {error}")
            return False
        if held is None and edit is not with_entry:
            return False
        text = (held or b"").decode("utf-8", "replace")
        try:
            changed = edit(tool, text, *arguments)
        except ValueError as error:
            self._log(f"comfyui: left {path} as it is: {error}")
            return False
        if changed is None:
            return False
        try:
            files.write(path, changed.encode("utf-8"), 0o600)
        except (OSError, ModuleApplyError) as error:
            self._log(f"comfyui: cannot write {path}: {error}")
            return False
        return True

    def _make_workspace(self, files, workspace: str) -> None:
        """Make the workspace and its links as the account.

        Raises:
            OSError: When the workspace cannot be made.
        """
        files.make_dir(workspace, umask=0o077)
        for name in COMFYUI_WORKSPACE_SOURCE_DIRS:
            self._link(files, self._join(self._source_dir, name), workspace, name)
        for name in COMFYUI_WORKSPACE_SHARED_DIRS:
            self._link(files, self._join(self._base_dir, name), workspace, name)
        for name in COMFYUI_WORKSPACE_SOURCE_FILES:
            target = self._join(self._source_dir, name)
            path = self._join(workspace, name)
            if self._os_name != "windows":
                self._link(files, target, workspace, name)
                continue
            try:
                with open(
                    os.path.join(self._module_dir, COMFYUI_SOURCE_DIR, name), "rb"
                ) as stream:
                    data = stream.read()
            except OSError as error:
                self._log(f"comfyui: cannot read {target}: {error}")
                continue
            if files.read(path) != data:
                files.write(path, data, 0o644)

    def _link(self, files, target: str, workspace: str, name: str) -> None:
        """One link in the workspace, made as the account; a file of the account's standing there is left."""
        path = self._join(workspace, name)
        if not files.link(target, path):
            self._log(f"comfyui: {path} is no link and stays as it is")
