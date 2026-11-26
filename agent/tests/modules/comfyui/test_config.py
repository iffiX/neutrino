"""The ComfyUI configuration: ``config_invalid {field}`` for a value outside its choices, a Mac naming no build and every other system one, and the idle unload times."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.comfyui.config import ComfyuiConfig, idle_seconds

CONFIG = {
    "secret": "s" * 32,
    "cookie_name": "neutrino_0123456789ab",
    "local_name": "comfyui-a.localhost",
    "torch_build": "cpu",
    "idle_unload": "30m",
    "account": "anna",
    "password": "",
    "tools": ["claude_code", "opencode"],
}


def test_a_configuration_inside_its_choices_passes():
    ComfyuiConfig.from_dict(CONFIG).validate("linux")
    ComfyuiConfig.from_dict({**CONFIG, "torch_build": ""}).validate("darwin")
    assert ComfyuiConfig.from_dict({**CONFIG, "torch_build": "cpu"}).is_cpu
    assert not ComfyuiConfig.from_dict({**CONFIG, "torch_build": "nvidia"}).is_cpu


@pytest.mark.parametrize(
    "change, field, os_name",
    [
        ({"torch_build": "rocm"}, "torch_build", "linux"),
        ({"torch_build": ""}, "torch_build", "windows"),
        ({"torch_build": "cpu"}, "torch_build", "darwin"),
        ({"idle_unload": "2h"}, "idle_unload", "linux"),
        ({"tools": ["gemini"]}, "tools", "linux"),
        ({"tools": "codex"}, "tools", "linux"),
        ({"account": 3}, "account", "linux"),
        ({"secret": ""}, "secret", "linux"),
    ],
)
def test_a_value_outside_its_choices_is_refused(change, field, os_name):
    with pytest.raises(ModuleApplyError) as caught:
        ComfyuiConfig.from_dict({**CONFIG, **change}).validate(os_name)
    assert caught.value.code == "config_invalid"
    assert caught.value.params == {"field": field}


def test_the_idle_unload_times_and_their_default():
    assert idle_seconds("5m") == 300
    assert idle_seconds("4h") == 14400
    assert idle_seconds("-1") is None
    assert ComfyuiConfig.from_dict({}).idle_unload == "30m"
