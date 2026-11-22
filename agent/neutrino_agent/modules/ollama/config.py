"""The Ollama module's settings: how long a model stays in memory, which GPUs.

The hub keeps them and sends them as the module's configuration,
``{keep_alive, gpus}``. ``keep_alive`` is one of five durations as Ollama
spells them; ``gpus`` is absent for every GPU, or the machine's GPUs in the
order its report lists them, each ``{vendor, is_used}``. They become
variables of the server's environment.

Pure: parsing, checking and the variables only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.ollama.constants import (
    OLLAMA_CODE_CONFIG_INVALID,
    OLLAMA_GPU_AMD,
    OLLAMA_GPU_APPLE,
    OLLAMA_GPU_CUDA_ORDER,
    OLLAMA_GPU_CUDA_VARIABLE,
    OLLAMA_GPU_FREE_OS,
    OLLAMA_GPU_NONE,
    OLLAMA_GPU_NVIDIA,
    OLLAMA_GPU_ROCM_VARIABLE,
    OLLAMA_GPU_VULKAN_VARIABLE,
    OLLAMA_KEEP_ALIVE_CHOICES,
    OLLAMA_KEEP_ALIVE_DEFAULT,
    OLLAMA_KEEP_ALIVE_VARIABLE,
)


def gpu_environment(gpus) -> dict:
    """The variables that keep the server off the GPUs not used. Pure.

    Args:
        gpus: The machine's GPUs in its report's order, each ``{vendor,
            is_used}``; None for every GPU.

    Returns:
        ``CUDA_VISIBLE_DEVICES`` with ``CUDA_DEVICE_ORDER`` for the NVIDIA
        cards, ``ROCR_VISIBLE_DEVICES`` for the AMD cards and
        ``GGML_VK_VISIBLE_DEVICES`` for every card that is neither NVIDIA's
        nor Apple's: each the places of the used cards among its group,
        ``-1`` when none is used, and set only while one of its group is
        not used.
    """
    cards = [gpu for gpu in gpus or [] if isinstance(gpu, dict)]
    groups = (
        (
            OLLAMA_GPU_CUDA_VARIABLE,
            [gpu for gpu in cards if gpu.get("vendor") == OLLAMA_GPU_NVIDIA],
        ),
        (
            OLLAMA_GPU_ROCM_VARIABLE,
            [gpu for gpu in cards if gpu.get("vendor") == OLLAMA_GPU_AMD],
        ),
        (
            OLLAMA_GPU_VULKAN_VARIABLE,
            [
                gpu
                for gpu in cards
                if gpu.get("vendor") not in (OLLAMA_GPU_NVIDIA, OLLAMA_GPU_APPLE)
            ],
        ),
    )
    environment = {}
    for variable, group in groups:
        if all(gpu.get("is_used") is True for gpu in group):
            continue
        used = [
            str(place) for place, gpu in enumerate(group) if gpu.get("is_used") is True
        ]
        environment[variable] = ",".join(used) or OLLAMA_GPU_NONE
        if variable == OLLAMA_GPU_CUDA_VARIABLE:
            environment.update(OLLAMA_GPU_CUDA_ORDER)
    return environment


@dataclass
class OllamaConfig:
    """What the module's configuration holds.

    Attributes:
        keep_alive: How long a model a request loaded stays in memory after
            its last request, as ``OLLAMA_KEEP_ALIVE`` spells it.
        gpus: The machine's GPUs, each ``{vendor, is_used}``; None for
            every GPU.
    """

    keep_alive: object = OLLAMA_KEEP_ALIVE_DEFAULT
    gpus: object = None

    @classmethod
    def from_dict(cls, data: dict) -> "OllamaConfig":
        """Read a configuration as the hub sent it, unchecked.

        Args:
            data: The configuration.

        Returns:
            The settings, the default duration where none is named.
        """
        return cls(
            keep_alive=data.get("keep_alive", OLLAMA_KEEP_ALIVE_DEFAULT),
            gpus=data.get("gpus"),
        )

    def validate(self) -> None:
        """Check the settings against their choices.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` for a duration
                outside the five, or a ``gpus`` that is not a list of
                ``{vendor, is_used}``.
        """
        if self.keep_alive not in OLLAMA_KEEP_ALIVE_CHOICES:
            raise ModuleApplyError(OLLAMA_CODE_CONFIG_INVALID, {"field": "keep_alive"})
        if self.gpus is None:
            return
        if not isinstance(self.gpus, list) or not all(
            isinstance(gpu, dict)
            and isinstance(gpu.get("vendor"), str)
            and isinstance(gpu.get("is_used"), bool)
            for gpu in self.gpus
        ):
            raise ModuleApplyError(OLLAMA_CODE_CONFIG_INVALID, {"field": "gpus"})

    def environment(self, os_name: str) -> dict:
        """The variables the server starts with for these settings.

        Args:
            os_name: ``linux``, ``windows`` or ``darwin``; macOS takes no
                GPU variable.

        Returns:
            ``OLLAMA_KEEP_ALIVE``, and the GPU variables of
            :func:`gpu_environment`.
        """
        environment = {OLLAMA_KEEP_ALIVE_VARIABLE: str(self.keep_alive)}
        if os_name != OLLAMA_GPU_FREE_OS and isinstance(self.gpus, list):
            environment.update(gpu_environment(self.gpus))
        return environment
