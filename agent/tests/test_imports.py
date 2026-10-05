"""Every module in the tree imports, and the tree is the one that survived.

A move that broke a path fails here, and so does a module the prune was
meant to take out coming back by accident.
"""

import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

import neutrino_agent

AGENT_ROOT = Path(__file__).resolve().parent.parent

# The standard library modules only POSIX has, which Windows lacks.
POSIX_ONLY_MODULES = ("pwd", "grp", "fcntl", "termios", "pty")

# The functions of ``os`` only POSIX has. A module that names one where it is
# imported, a default argument among those places, cannot be imported on
# Windows.
POSIX_ONLY_OS_NAMES = (
    "chown",
    "fchown",
    "lchown",
    "geteuid",
    "getuid",
    "getgid",
    "getegid",
    "setuid",
    "setgid",
    "setsid",
    "getpgid",
    "killpg",
    "initgroups",
    "setgroups",
    "getgroups",
    "mkfifo",
    "fork",
)

# Every module imported in a fresh interpreter that has none of them and no
# Unix sockets, the way Windows is.
WINDOWS_IMPORT_PROBE = """
import importlib, os, pkgutil, socket, sys
for name in {names!r}:
    sys.modules[name] = None
for name in {os_names!r}:
    if hasattr(os, name):
        delattr(os, name)
del socket.AF_UNIX
import neutrino_agent
for found in pkgutil.walk_packages(neutrino_agent.__path__, "neutrino_agent."):
    importlib.import_module(found.name)
"""

SURVIVING_MODULES = {
    "neutrino_agent.ai_tools",
    "neutrino_agent.ai_tools.account_lock",
    "neutrino_agent.ai_tools.account_session",
    "neutrino_agent.ai_tools.applier",
    "neutrino_agent.ai_tools.constants",
    "neutrino_agent.ai_tools.switcher",
    "neutrino_agent.ai_tools.switcher_copy",
    "neutrino_agent.cli",
    "neutrino_agent.cli.answer",
    "neutrino_agent.cli.entry",
    "neutrino_agent.cli.join",
    "neutrino_agent.cli.leave",
    "neutrino_agent.cli.rdp",
    "neutrino_agent.cli.run",
    "neutrino_agent.cli.service",
    "neutrino_agent.cli.start",
    "neutrino_agent.cli.status",
    "neutrino_agent.cli.step_down",
    "neutrino_agent.cli.stop",
    "neutrino_agent.cli.sync",
    "neutrino_agent.cli.wording",
    "neutrino_agent.constants",
    "neutrino_agent.control",
    "neutrino_agent.control.client",
    "neutrino_agent.control.server",
    "neutrino_agent.control.windows_pipe",
    "neutrino_agent.core",
    "neutrino_agent.core.channel",
    "neutrino_agent.core.commands",
    "neutrino_agent.core.desired_state",
    "neutrino_agent.core.engine",
    "neutrino_agent.core.enrollment",
    "neutrino_agent.core.loop",
    "neutrino_agent.core.metrics",
    "neutrino_agent.core.network",
    "neutrino_agent.core.self_update",
    "neutrino_agent.core.session",
    "neutrino_agent.core.store",
    "neutrino_agent.core.version",
    "neutrino_agent.core.ws_client",
    "neutrino_agent.exceptions",
    "neutrino_agent.modules",
    "neutrino_agent.modules.base",
    "neutrino_agent.modules.gitea",
    "neutrino_agent.modules.gitea.applier",
    "neutrino_agent.modules.gitea.config",
    "neutrino_agent.modules.gitea.constants",
    "neutrino_agent.modules.gitea.darwin_applier",
    "neutrino_agent.modules.gitea.renderer",
    "neutrino_agent.modules.gitea.runner",
    "neutrino_agent.modules.gitea.windows_applier",
    "neutrino_agent.modules.http_forward",
    "neutrino_agent.modules.installers",
    "neutrino_agent.modules.log_tail",
    "neutrino_agent.modules.package",
    "neutrino_agent.modules.powershell_run",
    "neutrino_agent.modules.podman",
    "neutrino_agent.modules.podman.applier",
    "neutrino_agent.modules.podman.config",
    "neutrino_agent.modules.podman.constants",
    "neutrino_agent.modules.podman.renderer",
    "neutrino_agent.modules.podman.runner",
    "neutrino_agent.modules.remote_desktop",
    "neutrino_agent.modules.rustdesk",
    "neutrino_agent.modules.samba",
    "neutrino_agent.modules.samba.applier",
    "neutrino_agent.modules.samba.config",
    "neutrino_agent.modules.samba.darwin_applier",
    "neutrino_agent.modules.samba.constants",
    "neutrino_agent.modules.samba.renderer",
    "neutrino_agent.modules.samba.runner",
    "neutrino_agent.modules.samba.windows_applier",
    "neutrino_agent.modules.subprocess_run",
    "neutrino_agent.modules.system_package",
    "neutrino_agent.modules.terminal",
    "neutrino_agent.modules.terminal.config",
    "neutrino_agent.modules.terminal.constants",
    "neutrino_agent.modules.terminal.runner",
    "neutrino_agent.modules.unpacked_tree",
    "neutrino_agent.modules.cloudcli",
    "neutrino_agent.modules.cloudcli.config",
    "neutrino_agent.modules.cloudcli.constants",
    "neutrino_agent.modules.cloudcli.darwin_applier",
    "neutrino_agent.modules.cloudcli.forwarder",
    "neutrino_agent.modules.cloudcli.installer",
    "neutrino_agent.modules.cloudcli.linux_applier",
    "neutrino_agent.modules.cloudcli.record_store",
    "neutrino_agent.modules.cloudcli.runner",
    "neutrino_agent.modules.cloudcli.windows_applier",
    "neutrino_agent.modules.code_server",
    "neutrino_agent.modules.code_server.config",
    "neutrino_agent.modules.code_server.constants",
    "neutrino_agent.modules.code_server.darwin_applier",
    "neutrino_agent.modules.code_server.forwarder",
    "neutrino_agent.modules.code_server.installer",
    "neutrino_agent.modules.code_server.linux_applier",
    "neutrino_agent.modules.code_server.runner",
    "neutrino_agent.modules.vscode",
    "neutrino_agent.modules.vscode.config",
    "neutrino_agent.modules.vscode.constants",
    "neutrino_agent.modules.vscode.darwin_applier",
    "neutrino_agent.modules.vscode.installer",
    "neutrino_agent.modules.vscode.linux_applier",
    "neutrino_agent.modules.vscode.runner",
    "neutrino_agent.modules.vscode.windows_applier",
    "neutrino_agent.modules.zfs",
    "neutrino_agent.modules.zfs.applier",
    "neutrino_agent.modules.zfs.config",
    "neutrino_agent.modules.zfs.constants",
    "neutrino_agent.modules.zfs.runner",
    "neutrino_agent.platforms",
    "neutrino_agent.platforms.answered_run",
    "neutrino_agent.platforms.base",
    "neutrino_agent.platforms.darwin",
    "neutrino_agent.platforms.detect",
    "neutrino_agent.platforms.linux",
    "neutrino_agent.platforms.win32",
    "neutrino_agent.platforms.windows",
    "neutrino_agent.platforms.windows_service",
    "neutrino_agent.rdp",
    "neutrino_agent.rdp.constants",
    "neutrino_agent.rdp.darwin_seat",
    "neutrino_agent.rdp.host",
    "neutrino_agent.rdp.linux_seat",
    "neutrino_agent.rdp.netstat",
    "neutrino_agent.rdp.seat",
    "neutrino_agent.rdp.windows_seat",
    "neutrino_agent.streams",
    "neutrino_agent.streams.channel",
    "neutrino_agent.streams.connect",
    "neutrino_agent.streams.connect_udp",
    "neutrino_agent.streams.files",
    "neutrino_agent.streams.log",
    "neutrino_agent.streams.module_command",
    "neutrino_agent.streams.package",
    "neutrino_agent.streams.shell",
    "neutrino_agent.streams.shell_session",
    "neutrino_agent.streams.windows_shell",
}


def found_modules() -> set:
    return {
        found.name
        for found in pkgutil.walk_packages(neutrino_agent.__path__, "neutrino_agent.")
    }


def test_every_module_imports():
    for name in sorted(found_modules()):
        importlib.import_module(name)


def test_the_tree_is_the_one_that_survived_the_prune():
    assert found_modules() == SURVIVING_MODULES


def test_every_module_imports_without_the_posix_only_modules():
    probe = WINDOWS_IMPORT_PROBE.format(
        names=POSIX_ONLY_MODULES, os_names=POSIX_ONLY_OS_NAMES
    )

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
