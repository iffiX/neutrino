"""The Ollama module's settings: their check and the variables they give.

What these pin: ``keep_alive`` is one of the five choices, ``30m`` while the
configuration names none; ``gpus`` is absent or a list of ``{vendor,
is_used}``; anything else is refused ``config_invalid {field}``. The
variables: ``OLLAMA_KEEP_ALIVE`` always; for each group of cards,
``CUDA_VISIBLE_DEVICES`` for NVIDIA's with ``CUDA_DEVICE_ORDER``,
``ROCR_VISIBLE_DEVICES`` for AMD's and ``GGML_VK_VISIBLE_DEVICES`` for every
card that is neither NVIDIA's nor Apple's, the places of the used cards
counted from 0 in the group, ``-1`` when none is used, and set only while
one of the group is not used; no GPU variable on macOS.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.ollama.config import OllamaConfig, gpu_environment


def _gpu(vendor, is_used=True):
    return {"vendor": vendor, "is_used": is_used}


def test_an_empty_configuration_keeps_models_for_thirty_minutes():
    config = OllamaConfig.from_dict({})
    config.validate()
    assert config.environment("linux") == {"OLLAMA_KEEP_ALIVE": "30m"}


@pytest.mark.parametrize("keep_alive", ["5m", "30m", "1h", "4h", "-1"])
def test_each_choice_is_taken_as_ollama_spells_it(keep_alive):
    config = OllamaConfig.from_dict({"keep_alive": keep_alive})
    config.validate()
    assert config.environment("windows")["OLLAMA_KEEP_ALIVE"] == keep_alive


@pytest.mark.parametrize(
    "data, field",
    [
        ({"keep_alive": "10m"}, "keep_alive"),
        ({"keep_alive": 300}, "keep_alive"),
        ({"gpus": "all"}, "gpus"),
        ({"gpus": [{"vendor": "nvidia"}]}, "gpus"),
        ({"gpus": [{"vendor": "nvidia", "is_used": "yes"}]}, "gpus"),
        ({"gpus": ["nvidia:0"]}, "gpus"),
    ],
)
def test_a_value_outside_the_settings_is_refused(data, field):
    with pytest.raises(ModuleApplyError) as refused:
        OllamaConfig.from_dict(data).validate()
    assert refused.value.code == "config_invalid"
    assert refused.value.params == {"field": field}


def test_every_card_used_sets_no_gpu_variable():
    assert gpu_environment(None) == {}
    assert gpu_environment([]) == {}
    assert gpu_environment([_gpu("nvidia"), _gpu("amd"), _gpu("intel")]) == {}


def test_nvidia_cards_are_named_by_their_place_in_pci_order():
    gpus = [_gpu("nvidia"), _gpu("nvidia", False), _gpu("nvidia")]
    assert gpu_environment(gpus) == {
        "CUDA_VISIBLE_DEVICES": "0,2",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
    }


def test_a_group_with_no_card_used_reads_minus_one():
    gpus = [_gpu("nvidia", False), _gpu("amd")]
    assert gpu_environment(gpus) == {
        "CUDA_VISIBLE_DEVICES": "-1",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
    }


def test_amd_cards_go_to_rocm_and_with_the_others_to_vulkan():
    gpus = [
        _gpu("nvidia"),
        _gpu("amd"),
        _gpu("intel"),
        _gpu("amd", False),
        _gpu("apple", False),
    ]
    assert gpu_environment(gpus) == {
        "ROCR_VISIBLE_DEVICES": "0",
        "GGML_VK_VISIBLE_DEVICES": "0,1",
    }


def test_an_unnamed_vendor_counts_among_the_vulkan_cards():
    gpus = [_gpu(""), _gpu("intel", False)]
    assert gpu_environment(gpus) == {"GGML_VK_VISIBLE_DEVICES": "0"}


def test_macos_takes_the_idle_time_alone():
    config = OllamaConfig.from_dict(
        {"keep_alive": "1h", "gpus": [_gpu("apple", False)]}
    )
    config.validate()
    assert config.environment("darwin") == {"OLLAMA_KEEP_ALIVE": "1h"}
    linux = OllamaConfig.from_dict({"keep_alive": "-1", "gpus": [_gpu("amd", False)]})
    assert linux.environment("linux") == {
        "OLLAMA_KEEP_ALIVE": "-1",
        "ROCR_VISIBLE_DEVICES": "-1",
        "GGML_VK_VISIBLE_DEVICES": "-1",
    }
