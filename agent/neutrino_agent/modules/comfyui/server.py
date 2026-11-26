"""How ComfyUI's server starts, the same on every system: its command line and its environment.

The service runs the venv's Python on ``source/main.py`` with ``--listen
127.0.0.1 --port <port> --base-directory <data directory>/data
--enable-manager``, and ``--cpu`` under the CPU build. Its environment is
written from scratch: ``HOME`` on Linux and macOS, the temporary folder,
the bytecode prefix, uv's cache and its two fixed variables, ``UV_STACK_SIZE``
on Windows, and the ``pypi`` set's first ranked source in the three
variables pip and uv read.

Pure: paths and text only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_BASE_DIR,
    COMFYUI_CPU_ARGUMENT,
    COMFYUI_HOST,
    COMFYUI_MAIN_NAME,
    COMFYUI_PYCACHE_DIR,
    COMFYUI_SERVER_ARGUMENTS,
    COMFYUI_SOURCE_DIR,
    COMFYUI_TMP_DIR,
    COMFYUI_UV_CACHE_DIR,
    COMFYUI_VENV_DIR,
)
from neutrino_agent.modules.shared.package import joiner
from neutrino_agent.modules.shared.python_env import environment_python, uv_variables

# The variables pip and uv read their index from, as the ``pypi`` set names
# them.
INDEX_VARIABLES = ("PIP_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX_URL")


@dataclass(frozen=True)
class ComfyuiServer:
    """What one start of the server takes.

    Attributes:
        port: ComfyUI's own port on ``127.0.0.1``.
        index_url: The ``pypi`` set's first ranked source; empty names none.
        is_cpu: Whether it runs on the CPU alone.
    """

    port: int
    index_url: str = ""
    is_cpu: bool = False


def server_command(
    server: ComfyuiServer, *, module_dir: str, data_dir: str, os_name: str
) -> list:
    """The server's command line. Pure.

    Args:
        server: What the start takes.
        module_dir: The module's directory.
        data_dir: The data directory.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        The argument vector.
    """
    join = joiner(os_name)
    command = [
        environment_python(join(data_dir, COMFYUI_VENV_DIR), os_name),
        join(module_dir, COMFYUI_SOURCE_DIR, COMFYUI_MAIN_NAME),
        "--listen",
        COMFYUI_HOST,
        "--port",
        str(int(server.port)),
        "--base-directory",
        join(data_dir, COMFYUI_BASE_DIR),
        *COMFYUI_SERVER_ARGUMENTS,
    ]
    if server.is_cpu:
        command.append(COMFYUI_CPU_ARGUMENT)
    return command


def server_environment(server: ComfyuiServer, *, data_dir: str, os_name: str) -> dict:
    """The server's environment, by name. Pure.

    Args:
        server: What the start takes.
        data_dir: The data directory.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        The variables.
    """
    join = joiner(os_name)
    temporary = join(data_dir, COMFYUI_TMP_DIR)
    environment = {
        **uv_variables(cache_dir=join(data_dir, COMFYUI_UV_CACHE_DIR), os_name=os_name),
        "PYTHONPYCACHEPREFIX": join(data_dir, COMFYUI_PYCACHE_DIR),
    }
    if os_name == "windows":
        environment.update({"TEMP": temporary, "TMP": temporary})
    else:
        environment.update({"HOME": data_dir, "TMPDIR": temporary})
    if server.index_url:
        environment.update({name: server.index_url for name in INDEX_VARIABLES})
    return environment
