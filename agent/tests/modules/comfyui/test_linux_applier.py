"""ComfyUI on Linux: the unit runs the venv's Python as ``neutrino_comfyui`` with ``UMask=0027`` and the server's environment, and a command as the service's account starts in the data directory under umask 077 with its environment written from scratch."""

import types

from neutrino_agent.modules.comfyui.linux_applier import (
    ComfyuiLinuxApplier,
    render_unit,
    scratch_command,
)
from neutrino_agent.modules.comfyui.server import ComfyuiServer

SERVER = ComfyuiServer(port=15000, index_url="https://pypi.org/simple", is_cpu=True)


def test_the_unit_runs_the_venvs_python_as_the_account_with_its_umask():
    unit = render_unit(
        SERVER,
        module_dir="/var/lib/neutrino/agent/comfyui",
        data_dir="/var/lib/neutrino/agent/comfyui_data",
    )
    assert "User=neutrino_comfyui\n" in unit
    assert "UMask=0027\n" in unit
    assert (
        "ExecStart=/var/lib/neutrino/agent/comfyui_data/venv/bin/python "
        "/var/lib/neutrino/agent/comfyui/source/main.py --listen 127.0.0.1 --port 15000 "
        "--base-directory /var/lib/neutrino/agent/comfyui_data/data --enable-manager --cpu\n"
    ) in unit
    assert "Environment=UV_INDEX_URL=https://pypi.org/simple\n" in unit
    assert "Environment=HOME=/var/lib/neutrino/agent/comfyui_data\n" in unit
    assert "WantedBy=multi-user.target" in unit


class Files:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.argvs = []

    def run(self, argv):
        self.argvs.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout=b"done", stderr=b"")


def test_a_command_as_the_service_runs_in_the_data_directory_from_scratch(tmp_path):
    made = []

    def factory(**kwargs):
        made.append(Files(**kwargs))
        return made[-1]

    applier = ComfyuiLinuxApplier(state_dir=str(tmp_path), files_factory=factory)
    code, output = applier.run_as_service(
        ["/m/uv/uv", "pip", "check"], {"UV_NO_CONFIG": "1"}, 900
    )
    assert code == 0 and "done" in output
    assert made[0].kwargs["account"] == "neutrino_comfyui"
    assert made[0].kwargs["timeout_s"] == 900
    argv = made[0].argvs[0]
    assert argv[:4] == [
        "/bin/sh",
        "-c",
        'cd -- "$0" && umask 077 && exec "$@"',
        applier.data_dir,
    ]
    assert argv[4:] == [
        "/usr/bin/env",
        "-i",
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "UV_NO_CONFIG=1",
        "/m/uv/uv",
        "pip",
        "check",
    ]
    assert scratch_command(["x"], {"A": "1"})[:2] == ["/usr/bin/env", "-i"]
