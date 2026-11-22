"""Ollama on Linux: the unit, the account, the data directory, a person's unit.

What these pin: the unit runs ``ollama serve`` as ``neutrino_ollama`` with
``HOME``, ``OLLAMA_HOST``, ``OLLAMA_MODELS`` and ``OLLAMA_NO_CLOUD``; an
apply writes it only when it differs, enables and starts it, restarts it
only on a change, and under ``stopped`` writes it alone; a stop disables it;
an uninstall removes the unit and the program and keeps the data directory;
the account is made as a system account with no login shell in the GPU
groups the machine has, and a data directory another uid owns is handed
over; a person's unit is found in its three places, driven through
``systemctl`` alone and put back as it was found. The settings' variables
go into the unit, a change of them restarts it, and on a person's unit they
go into a drop-in of the module's own, which a changed write restarts the
unit for and which its removal takes away with a restart of a running unit,
with its folder when nothing of the person's is in it.
"""

import os
from types import SimpleNamespace

from neutrino_agent.modules.ollama import linux_applier
from neutrino_agent.modules.ollama.linux_applier import (
    OllamaLinuxApplier,
    render_unit,
)


class Result:
    def __init__(self, exit_code=0, stdout=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = ""

    @property
    def is_success(self):
        return self.exit_code == 0


class FakeSystem:
    """The commands an applier runs, answered from a table of states."""

    def __init__(self):
        self.commands: list = []
        self.units = {}
        self.missing = set()

    def run(self, command, *, is_checked=True, **kwargs):
        self.commands.append(list(command))
        if command[:2] == ["systemctl", "is-active"]:
            return Result(0, self.units.get(command[2], "inactive") + "\n")
        if command[:2] == ["systemctl", "is-enabled"]:
            return Result(0, "enabled\n" if command[2] in self.units else "disabled\n")
        if command[0] == "id":
            return Result(1 if command[1] in self.missing else 0)
        if command[:2] == ["getent", "group"]:
            return Result(0 if command[2] == "render" else 2)
        return Result(0)


def _applier(tmp_path, system, monkeypatch):
    monkeypatch.setattr(
        linux_applier,
        "unit_state",
        lambda unit: system.units.get(unit, "inactive"),
    )
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    applier = OllamaLinuxApplier(
        state_dir=str(tmp_path / "state"),
        run_command=system.run,
        systemd_dir=str(systemd),
        person_unit_paths=(str(tmp_path / "etc" / "ollama.service"),),
    )
    monkeypatch.setattr(applier, "_prepare_data", lambda account: None)
    return applier


def test_the_unit_runs_ollama_serve_with_the_module_s_environment(tmp_path):
    text = render_unit("/var/lib/neutrino/agent/ollama/ollama/bin/ollama", "/data")
    assert "User=neutrino_ollama\n" in text
    assert "ExecStart=/var/lib/neutrino/agent/ollama/ollama/bin/ollama serve\n" in text
    assert "Environment=HOME=/data\n" in text
    assert "Environment=OLLAMA_HOST=127.0.0.1:11434\n" in text
    assert "Environment=OLLAMA_MODELS=/data/models\n" in text
    assert "Environment=OLLAMA_NO_CLOUD=1\n" in text
    assert "Restart=always\n" in text
    assert "WantedBy=multi-user.target\n" in text


def test_an_apply_writes_the_unit_starts_it_and_restarts_only_on_a_change(
    tmp_path, monkeypatch
):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    assert applier.apply(is_started=False) == "written"
    assert [
        "systemctl",
        "enable",
        "--now",
        "neutrino_ollama.service",
    ] not in system.commands
    assert applier.apply(is_started=True) == "started"
    assert system.commands[-1] == [
        "systemctl",
        "enable",
        "--now",
        "neutrino_ollama.service",
    ]
    system.units["neutrino_ollama.service"] = "active"
    system.commands.clear()
    assert applier.apply(is_started=True) == "unchanged"
    assert system.commands == []
    (tmp_path / "systemd" / "neutrino_ollama.service").write_text("old")
    assert applier.apply(is_started=True) == "restarted"
    assert system.commands[-1] == ["systemctl", "restart", "neutrino_ollama.service"]


def test_a_stop_disables_and_an_uninstall_keeps_the_data(tmp_path, monkeypatch):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    applier.apply(is_started=True)
    applier.stop()
    assert system.commands[-1] == [
        "systemctl",
        "disable",
        "--now",
        "neutrino_ollama.service",
    ]
    data = tmp_path / "state" / "ollama_data" / "models"
    data.mkdir(parents=True)
    os.makedirs(os.path.dirname(applier.program_path))
    open(applier.program_path, "w").close()
    applier.uninstall()
    assert not (tmp_path / "systemd" / "neutrino_ollama.service").exists()
    assert not os.path.exists(applier.module_dir)
    assert data.is_dir()


def test_the_account_is_a_system_account_in_the_gpu_groups(tmp_path, monkeypatch):
    system = FakeSystem()
    system.missing.add("neutrino_ollama")
    applier = _applier(tmp_path, system, monkeypatch)
    me = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    monkeypatch.setattr(linux_applier, "pwd", SimpleNamespace(getpwnam=lambda name: me))
    assert applier.ensure_account() is False
    made = [command for command in system.commands if command[0] == "useradd"][0]
    assert made[:4] == ["useradd", "--system", "--no-create-home", "--home-dir"]
    assert made[4] == applier.data_dir
    assert "neutrino ollama" in made and made[-1] == "neutrino_ollama"
    assert ["usermod", "-a", "-G", "render", "neutrino_ollama"] in system.commands


def test_a_data_directory_another_uid_owns_is_handed_over(tmp_path, monkeypatch):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    os.makedirs(applier.data_dir)
    other = SimpleNamespace(pw_uid=os.getuid() + 1, pw_gid=os.getgid())
    monkeypatch.setattr(
        linux_applier, "pwd", SimpleNamespace(getpwnam=lambda name: other)
    )
    given = []
    monkeypatch.setattr(
        linux_applier,
        "give_tree",
        lambda path, uid, gid: given.append((path, uid, gid)) or [],
    )
    assert applier.ensure_account() is True
    assert given == [(applier.data_dir, os.getuid() + 1, os.getgid())]


def test_a_person_s_unit_is_found_driven_and_put_back(tmp_path, monkeypatch):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    assert applier.person_unit_path() == ""
    unit = tmp_path / "etc" / "ollama.service"
    unit.parent.mkdir()
    unit.write_text("[Service]\n")
    assert applier.person_unit_path() == str(unit)
    system.units["ollama.service"] = "active"
    assert applier.person_unit_state() == {"is_enabled": True, "is_active": True}
    applier.stop_person()
    assert system.commands[-1] == ["systemctl", "disable", "--now", "ollama.service"]
    system.commands.clear()
    applier.restore_person({"is_enabled": False, "is_active": True})
    assert system.commands == [
        ["systemctl", "disable", "ollama.service"],
        ["systemctl", "start", "ollama.service"],
    ]
    assert not any("useradd" in command for command in system.commands)


def test_the_settings_variables_go_into_the_unit_and_restart_it(tmp_path, monkeypatch):
    text = render_unit(
        "/p/ollama",
        "/data",
        environment={"OLLAMA_KEEP_ALIVE": "-1", "CUDA_VISIBLE_DEVICES": "0,2"},
    )
    assert "Environment=OLLAMA_KEEP_ALIVE=-1\n" in text
    assert "Environment=CUDA_VISIBLE_DEVICES=0,2\n" in text
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}, is_started=True)
    system.units["neutrino_ollama.service"] = "active"
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "30m"}) == "unchanged"
    assert applier.apply(environment={"OLLAMA_KEEP_ALIVE": "5m"}) == "restarted"
    unit = (tmp_path / "systemd" / "neutrino_ollama.service").read_text()
    assert "Environment=OLLAMA_KEEP_ALIVE=5m\n" in unit


def test_a_person_s_unit_takes_the_settings_through_a_drop_in(tmp_path, monkeypatch):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    drop_in = tmp_path / "systemd" / "ollama.service.d" / "neutrino.conf"
    settings = {"OLLAMA_KEEP_ALIVE": "30m", "ROCR_VISIBLE_DEVICES": "1"}
    assert applier.apply_person(environment=settings, is_started=False) == "written"
    assert drop_in.read_text() == (
        "[Service]\n"
        "Environment=OLLAMA_KEEP_ALIVE=30m\n"
        "Environment=ROCR_VISIBLE_DEVICES=1\n"
    )
    assert system.commands == [["systemctl", "daemon-reload"]]
    system.commands.clear()
    assert applier.apply_person(environment=settings, is_started=True) == "started"
    assert system.commands == [["systemctl", "enable", "--now", "ollama.service"]]
    system.units["ollama.service"] = "active"
    system.commands.clear()
    assert applier.apply_person(environment=settings) == "started"
    assert system.commands == [["systemctl", "enable", "--now", "ollama.service"]]
    system.commands.clear()
    settings = {"OLLAMA_KEEP_ALIVE": "4h"}
    assert applier.apply_person(environment=settings) == "restarted"
    assert system.commands == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "ollama.service"],
        ["systemctl", "restart", "ollama.service"],
    ]
    assert not (tmp_path / "systemd" / "neutrino_ollama.service").exists()


def test_the_drop_in_s_removal_restarts_a_running_unit(tmp_path, monkeypatch):
    system = FakeSystem()
    applier = _applier(tmp_path, system, monkeypatch)
    assert applier.remove_person_settings() is False
    assert system.commands == []
    applier.apply_person(environment={"OLLAMA_KEEP_ALIVE": "1h"}, is_started=False)
    system.commands.clear()
    assert applier.remove_person_settings() is True
    assert not (tmp_path / "systemd" / "ollama.service.d").exists()
    assert system.commands == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "try-restart", "ollama.service"],
    ]
    applier.apply_person(environment={"OLLAMA_KEEP_ALIVE": "1h"}, is_started=False)
    own = tmp_path / "systemd" / "ollama.service.d" / "override.conf"
    own.write_text("[Service]\n")
    assert applier.remove_person_settings() is True
    assert own.read_text() == "[Service]\n"
