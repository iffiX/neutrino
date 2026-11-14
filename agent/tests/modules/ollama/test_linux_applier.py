"""Ollama on Linux: the unit, the account, the data directory, a person's unit.

What these pin: the unit runs ``ollama serve`` as ``neutrino_ollama`` with
``HOME``, ``OLLAMA_HOST``, ``OLLAMA_MODELS`` and ``OLLAMA_NO_CLOUD``; an
apply writes it only when it differs, enables and starts it, restarts it
only on a change, and under ``stopped`` writes it alone; a stop disables it;
an uninstall removes the unit and the program and keeps the data directory;
the account is made as a system account with no login shell in the GPU
groups the machine has, and a data directory another uid owns is handed
over; a person's unit is found in its three places, driven through
``systemctl`` alone and put back as it was found.
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
    applier.start_person()
    assert system.commands[-1] == ["systemctl", "enable", "--now", "ollama.service"]
    applier.stop_person()
    assert system.commands[-1] == ["systemctl", "disable", "--now", "ollama.service"]
    system.commands.clear()
    applier.restore_person({"is_enabled": False, "is_active": True})
    assert system.commands == [
        ["systemctl", "disable", "ollama.service"],
        ["systemctl", "start", "ollama.service"],
    ]
    assert not any("useradd" in command for command in system.commands)
