"""The server's command line with ``--cpu`` under the CPU build alone, and its environment written from scratch with the ``pypi`` set's first source in its three variables."""

from neutrino_agent.modules.comfyui.server import (
    ComfyuiServer,
    server_command,
    server_environment,
)


def test_the_command_line_names_the_base_directory_and_cpu_under_the_cpu_build_alone():
    command = server_command(
        ComfyuiServer(port=15000, is_cpu=True),
        module_dir="/s/comfyui",
        data_dir="/s/comfyui_data",
        os_name="linux",
    )
    assert command == [
        "/s/comfyui_data/venv/bin/python",
        "/s/comfyui/source/main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        "15000",
        "--base-directory",
        "/s/comfyui_data/data",
        "--enable-manager",
        "--cpu",
    ]
    gpu = server_command(
        ComfyuiServer(port=15000),
        module_dir="C:\\s\\comfyui",
        data_dir="C:\\s\\comfyui_data",
        os_name="windows",
    )
    assert gpu[0] == "C:\\s\\comfyui_data\\venv\\Scripts\\python.exe"
    assert "--cpu" not in gpu


def test_the_environment_is_written_from_scratch():
    linux = server_environment(
        ComfyuiServer(port=1, index_url="https://pypi.org/simple"),
        data_dir="/d",
        os_name="linux",
    )
    assert linux == {
        "HOME": "/d",
        "TMPDIR": "/d/tmp",
        "PYTHONPYCACHEPREFIX": "/d/pycache",
        "UV_CACHE_DIR": "/d/uv_cache",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_CONFIG": "1",
        "PIP_INDEX_URL": "https://pypi.org/simple",
        "UV_DEFAULT_INDEX": "https://pypi.org/simple",
        "UV_INDEX_URL": "https://pypi.org/simple",
    }
    windows = server_environment(
        ComfyuiServer(port=1), data_dir="C:\\d", os_name="windows"
    )
    assert windows["TEMP"] == windows["TMP"] == "C:\\d\\tmp"
    assert windows["UV_STACK_SIZE"] == "16777216"
    assert "HOME" not in windows and "PIP_INDEX_URL" not in windows
