"""The readings two platforms share: nvidia-smi's CSV and the processes a
report lists.

``nvidia-smi`` is faked at ``shutil.which`` and ``subprocess.run``. What is
pinned is what its output is turned into, and which processes a report
carries.
"""

import subprocess

import neutrino_agent.core.metrics as metrics_module
from neutrino_agent.constants import AGENT_NVIDIA_SMI_COMMAND, AGENT_PROCESS_TOP_COUNT
from neutrino_agent.core.metrics import (
    ProcessMetrics,
    busiest_processes,
    gpu_vendor,
    parse_nvidia_smi,
    read_nvidia_gpus,
)

NVIDIA_SMI_SAMPLE = """NVIDIA GeForce RTX 4090, 87, 20123, 24564, 71, 402.50
NVIDIA T4, [N/A], 0, 15360, 40, [N/A]
garbled line
"""


def present(name):
    return f"/usr/bin/{name}"


def absent(name):
    return None


def test_each_nvidia_smi_line_is_one_card_and_a_missing_value_is_empty():
    gpus = [gpu.to_dict() for gpu in parse_nvidia_smi(NVIDIA_SMI_SAMPLE)]

    assert gpus == [
        {
            "vendor": "nvidia",
            "name": "NVIDIA GeForce RTX 4090",
            "utilization_percent": 87.0,
            "memory_used_mb": 20123,
            "memory_total_mb": 24564,
            "temperature_c": 71.0,
            "power_w": 402.5,
        },
        {
            "vendor": "nvidia",
            "name": "NVIDIA T4",
            "utilization_percent": None,
            "memory_used_mb": 0,
            "memory_total_mb": 15360,
            "temperature_c": 40.0,
            "power_w": None,
        },
    ]


def test_nvidia_smi_is_run_only_where_it_is_installed(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, NVIDIA_SMI_SAMPLE, "")

    monkeypatch.setattr(metrics_module.subprocess, "run", run)
    monkeypatch.setattr(metrics_module.shutil, "which", absent)
    assert read_nvidia_gpus() == []
    assert commands == []

    monkeypatch.setattr(metrics_module.shutil, "which", present)
    assert len(read_nvidia_gpus()) == 2
    assert commands == [AGENT_NVIDIA_SMI_COMMAND]


def test_a_failing_nvidia_smi_is_no_cards(monkeypatch):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 9, "", "no devices")

    monkeypatch.setattr(metrics_module.shutil, "which", present)
    monkeypatch.setattr(metrics_module.subprocess, "run", run)

    assert read_nvidia_gpus() == []


def test_the_busiest_processes_lead_by_processor_then_memory():
    processes = [
        ProcessMetrics(pid=pid, user="pat", name=f"p{pid}", memory_percent=pid)
        for pid in range(1, 30)
    ]
    processes.append(ProcessMetrics(pid=99, user="pat", name="busy", cpu_percent=5))

    chosen = busiest_processes(processes)

    assert len(chosen) == AGENT_PROCESS_TOP_COUNT
    assert [process.pid for process in chosen[:3]] == [99, 29, 28]


def test_a_card_s_vendor_is_what_its_name_or_driver_says():
    assert gpu_vendor("NVIDIA GeForce RTX 3060") == "nvidia"
    assert gpu_vendor("AMD Radeon Pro 5500M") == "amd"
    assert gpu_vendor("Intel(R) UHD Graphics 630") == "intel"
    assert gpu_vendor("Apple M1") == "apple"
    assert gpu_vendor("AGXAcceleratorG13X") == "apple"
    assert gpu_vendor("Red Hat QXL controller") == ""
