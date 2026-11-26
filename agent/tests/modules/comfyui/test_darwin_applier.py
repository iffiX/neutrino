"""ComfyUI on macOS: the LaunchDaemon names ``UserName``, ``GroupName`` and ``Umask`` 23, runs the venv's Python in the data directory, and writes its output in the agent's log folder."""

import plistlib

from neutrino_agent.modules.comfyui.darwin_applier import render_plist
from neutrino_agent.modules.comfyui.server import ComfyuiServer

SERVER = ComfyuiServer(port=15000, index_url="https://pypi.org/simple", is_cpu=True)


def test_the_launch_daemon_runs_as_the_account_with_umask_23():
    plist = plistlib.loads(
        render_plist(
            SERVER, module_dir="/S/comfyui", data_dir="/S/comfyui_data", group="staff"
        )
    )
    assert plist["Label"] == "com.neutrino.comfyui"
    assert plist["UserName"] == "neutrino_comfyui"
    assert plist["GroupName"] == "staff"
    assert plist["Umask"] == 23
    assert plist["ProgramArguments"][0] == "/S/comfyui_data/venv/bin/python"
    assert plist["StandardOutPath"] == "/Library/Logs/Neutrino/agent/comfyui.log"
    assert plist["EnvironmentVariables"]["HOME"] == "/S/comfyui_data"
    assert plist["WorkingDirectory"] == "/S/comfyui_data"
