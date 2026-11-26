"""The ComfyUI runner: the install's plan, the two locks, the configure, idle unload's start, the uninstall.

What these pin, against a faked applier that records what it is asked and
a faked uv: the install plans every archive and ``mcp``, ``verify``, then
``account neutrino_comfyui`` on Linux and macOS, then ``venv``, and no
``account`` on Windows; an artifact the record holds at the recipe's digest
is left out of the plan; ``mcp`` installs as root with ``--no-build`` and
is sealed; ``venv`` is made as the service's account with no seed and its
lock installed in two parts, ``pytorch`` first, then ``uv pip check``, and
no ``uv pip sync``; the lock's digest kept, and another lock stopping
ComfyUI, removing ``venv/``, making it again and installing each custom
node's ``requirements.txt`` after it; the Visual C++ DLLs copied beside
``python.exe`` with the Python's own kept; the configure taking both ports,
writing the default account's entries and comfy-mcp, writing and starting
the service and waiting for ``/system_stats``, ``apply_failed`` after 300
seconds; a change of the ``pypi`` set's first source alone keeping the
service as it is written; no account reached while ``account`` is empty;
the uninstall taking the tools' entries, the module's directory, the venv
and the caches as the service, and keeping ``data/``.
"""

import os
import zipfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.comfyui.runner import ComfyuiModuleRunner
from neutrino_agent.modules.shared.base import ModuleStep
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.platforms.base import AgentPlatform

LOCK = """\
numpy==2.5.5 \\
    --hash=sha256:aaaa
    # from https://pypi.org/simple
torch==2.15.0+cpu \\
    --hash=sha256:cccc
    # from https://download.pytorch.org/whl/cpu
"""
SETS = {
    "pypi": {"probe": "/numpy/", "sources": ["https://pypi.org/simple"]},
    "pytorch": {
        "probe": "/cpu/torch/",
        "sources": ["https://download.pytorch.org/whl"],
    },
}
CONFIG = {
    "secret": "s" * 32,
    "cookie_name": "neutrino_0123456789ab",
    "local_name": "comfyui-a.localhost",
    "torch_build": "cpu",
    "idle_unload": "30m",
    "account": "anna",
    "password": "",
    "tools": ["codex"],
}


def recipe(venv_digest="sha256:" + "1" * 64, *, is_windows=False):
    artifacts = [
        {
            "name": "python",
            "kind": "tar_gz",
            "directory": "python",
            "digest": "sha256:" + "a" * 64,
        },
        {
            "name": "uv",
            "kind": "tar_gz",
            "directory": "uv",
            "digest": "sha256:" + "b" * 64,
        },
        {
            "name": "source",
            "kind": "tar_gz",
            "directory": "source",
            "digest": "git-tree:" + "c" * 40,
        },
    ]
    if is_windows:
        artifacts.append(
            {
                "name": "vc_runtime",
                "kind": "zip",
                "member": "msvc_runtime-1.data/data",
                "digest": "sha256:" + "d" * 64,
            }
        )
    artifacts += [
        {
            "name": "mcp",
            "kind": "uv_lock",
            "digest": "sha256:" + "e" * 64,
            "source_sets": ["pypi"],
        },
        {
            "name": "venv",
            "kind": "uv_lock",
            "digest": venv_digest,
            "source_sets": ["pytorch", "pypi"],
        },
    ]
    return {
        "runner": "comfyui",
        "method": "hub",
        "params": {"version": "0.46.0", "artifacts": artifacts},
    }


class Platform(AgentPlatform):
    def __init__(self, root, os_name="linux"):
        self.root = str(root)
        self.os_name = os_name
        self.opened = []

    def agent_var_dir(self):
        return self.root

    def label_programs(self, path):
        pass

    def has_account(self, account):
        return account in ("anna", "neutrino_comfyui")

    def open_to_accounts(self, directory):
        self.opened.append(directory)


class Applier:
    """An applier of one system, recording what the runner asks; uv as the service answers from ``answers``."""

    def __init__(self, root, *, account="neutrino_comfyui", os_name="linux"):
        self.os_name = os_name
        self.account = account
        self.module_dir = os.path.join(str(root), "comfyui")
        self.data_dir = os.path.join(str(root), "comfyui_data")
        self.base_dir = os.path.join(self.data_dir, "data")
        self.calls = []
        self.runs = []
        self.text = ""
        self.active = False

    def ensure_account(self, *, log=None):
        self.calls.append("ensure_account")
        return False

    def prepare_data(self):
        self.calls.append("prepare_data")
        for name in ("models", "input", "output", "user", "custom_nodes"):
            os.makedirs(os.path.join(self.base_dir, name), exist_ok=True)

    def run_as_service(self, argv, environment, timeout_s):
        self.runs.append((list(argv), dict(environment)))
        if argv[1] == "venv":
            python = os.path.join(argv[-1], "bin", "python")
            os.makedirs(os.path.dirname(python), exist_ok=True)
            open(python, "w").close()
        return 0, ""

    def remove_as_service(self, path):
        self.calls.append(("remove", path))
        if os.path.isdir(path):
            import shutil

            shutil.rmtree(path)

    def write_access(self, account):
        self.calls.append(("access", account))
        return []

    def service_text(self, server):
        return f"port={server.port} index={server.index_url} cpu={server.is_cpu}"

    def written_text(self):
        return self.text

    def apply(self, server, *, is_started=True):
        self.calls.append(("apply", server, is_started))
        self.text = self.service_text(server)
        self.active = is_started
        return "started" if is_started else "written"

    def stop(self):
        self.calls.append("stop")
        self.active = False

    def is_active(self):
        return self.active

    def uninstall(self):
        self.calls.append("uninstall")

    def journal_units(self):
        return []

    def output_path(self):
        return ""


class Wiring:
    def __init__(self):
        self.calls = []
        self.program = "/m/mcp/bin/comfy-mcp"

    def apply(self, **kwargs):
        self.calls.append(("apply", kwargs))
        return list(kwargs["tools"])

    def remove(self, **kwargs):
        self.calls.append(("remove", kwargs))


class Idle:
    def __init__(self):
        self.calls = []

    def take(self, port, idle_s):
        self.calls.append(("take", port, idle_s))

    def stop(self):
        self.calls.append("stop")


class Forwarder:
    def __init__(self, record):
        self.record = record
        self.is_listening = True
        self.closed = False

    def matches(self, record):
        return record.get("port") == self.record.get("port")

    def start(self):
        pass

    def close(self):
        self.closed = True


def ranked_probe(url, source=""):
    from neutrino_agent.modules.shared.source_fetch import SourceProbe

    return SourceProbe(source=source, is_answered=False)


def make(
    tmp_path, *, os_name="linux", account="neutrino_comfyui", stats=True, clock=None
):
    applier = Applier(tmp_path, account=account, os_name=os_name)
    wiring = Wiring()
    idle = Idle()
    root_runs = []

    def run_root(cache, argv):
        root_runs.append(list(argv))
        if argv[1] == "venv":
            os.makedirs(os.path.join(argv[-1], "bin"), exist_ok=True)
        return 0, ""

    now = [0.0]
    runner = ComfyuiModuleRunner(
        platform=Platform(tmp_path, os_name),
        log=lambda line: None,
        applier=applier,
        wiring=wiring,
        idle=idle,
        forwarder_factory=lambda record, hooks, log: Forwarder(record),
        read_stats=(lambda port: stats) if not callable(stats) else stats,
        probe_one=ranked_probe,
        is_free=lambda port: True,
        run_root=run_root,
        clock=clock or (lambda: now[0]),
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    runner.take_source_sets(SETS)
    runner.take_recipe(recipe(is_windows=os_name == "windows"))
    runner.take_config(CONFIG)
    return runner, applier, wiring, idle, root_runs


def planned(runner, the_recipe):
    from neutrino_agent.modules.shared.package import received_artifacts

    steps = [
        ModuleStep(name="artifact", params={"name": artifact["name"]}, run=None)
        for artifact in received_artifacts(the_recipe)
    ]
    steps.append(ModuleStep(name="verify", run=None))
    return [
        (step.name, step.params.get("name") or step.params.get("account") or "")
        for step in runner.install_steps(the_recipe, steps)
    ]


def lock_file(tmp_path, text=LOCK):
    path = tmp_path / "lock.txt"
    path.write_text(text)
    return str(path)


def test_the_install_plans_the_account_before_the_venv(tmp_path):
    runner, *_ = make(tmp_path)
    assert planned(runner, recipe()) == [
        ("artifact", "python"),
        ("artifact", "uv"),
        ("artifact", "source"),
        ("artifact", "mcp"),
        ("verify", ""),
        ("account", "neutrino_comfyui"),
        ("artifact", "venv"),
    ]
    windows, *_ = make(tmp_path / "w", os_name="windows", account="")
    assert planned(windows, recipe(is_windows=True)) == [
        ("artifact", "python"),
        ("artifact", "uv"),
        ("artifact", "source"),
        ("artifact", "vc_runtime"),
        ("artifact", "mcp"),
        ("verify", ""),
        ("artifact", "venv"),
    ]


def test_mcp_installs_as_root_with_wheels_alone_and_is_sealed(tmp_path):
    runner, _applier, _wiring, _idle, root_runs = make(tmp_path)
    os.makedirs(os.path.join(runner.module_dir), exist_ok=True)
    runner.install_artifact(
        recipe(), recipe()["params"]["artifacts"][3], lock_file(tmp_path)
    )
    assert root_runs[0][1] == "venv" and "--seed" not in root_runs[0]
    installs = [argv for argv in root_runs if argv[1:3] == ["pip", "install"]]
    assert installs and all("--no-build" in argv for argv in installs)
    assert root_runs[-1][1:3] == ["pip", "check"]
    mcp = os.path.join(runner.module_dir, "mcp")
    assert os.stat(mcp).st_mode & 0o222 == 0
    remove_tree(mcp)


def test_the_venv_is_made_as_the_service_and_its_lock_installed_in_two_parts(tmp_path):
    runner, applier, *_ = make(tmp_path)
    artifact = recipe()["params"]["artifacts"][-1]
    runner.install_artifact(recipe(), artifact, lock_file(tmp_path))
    argvs = [argv for argv, _environment in applier.runs]
    assert argvs[0][1] == "venv" and "--seed" not in argvs[0]
    assert argvs[0][-1] == os.path.join(applier.data_dir, "venv")
    installs = [argv for argv in argvs if argv[1:3] == ["pip", "install"]]
    assert [argv[argv.index("--index-url") + 1] for argv in installs] == [
        "https://download.pytorch.org/whl/cpu",
        "https://pypi.org/simple",
    ]
    assert all("--require-hashes" in argv and "--no-deps" in argv for argv in installs)
    assert argvs[-1][1:3] == ["pip", "check"]
    assert all("sync" not in argv for argv in argvs)
    environment = applier.runs[0][1]
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert environment["UV_NO_CONFIG"] == "1"
    assert runner._record()["lock_digest"] == artifact["digest"]


def test_another_lock_makes_the_venv_again_with_comfyui_stopped_and_the_nodes_packages_after(
    tmp_path,
):
    runner, applier, *_ = make(tmp_path)
    runner.install_artifact(
        recipe(), recipe()["params"]["artifacts"][-1], lock_file(tmp_path)
    )
    node = os.path.join(applier.base_dir, "custom_nodes", "ComfyUI-GGUF")
    os.makedirs(node)
    open(os.path.join(node, "requirements.txt"), "w").write("gguf>=0.13.0\n")
    applier.runs.clear()
    applier.calls.clear()
    other = recipe("sha256:" + "2" * 64)
    assert runner.is_install_owed(other)
    assert ("artifact", "venv") in planned(runner, other)
    runner.install_artifact(
        other, other["params"]["artifacts"][-1], lock_file(tmp_path)
    )
    assert applier.calls.index("stop") < applier.calls.index(
        ("remove", os.path.join(applier.data_dir, "venv"))
    )
    argvs = [argv for argv, _environment in applier.runs]
    assert argvs[0][1] == "venv"
    assert argvs[-1][-1] == os.path.join(node, "requirements.txt")
    assert "--require-hashes" not in argvs[-1]
    assert runner._record()["lock_digest"] == "sha256:" + "2" * 64


def test_an_artifact_in_place_at_the_recipes_digest_is_left_out(tmp_path):
    runner, *_ = make(tmp_path)
    for name in ("python", "uv", "source", "mcp"):
        os.makedirs(os.path.join(runner.module_dir, name, "bin"), exist_ok=True)
    open(os.path.join(runner.module_dir, "python", "bin", "python3"), "w").close()
    open(os.path.join(runner.module_dir, "uv", "uv"), "w").close()
    for artifact in recipe()["params"]["artifacts"][:4]:
        runner._keep_digest(artifact["name"], artifact["digest"])
    assert planned(runner, recipe()) == [
        ("verify", ""),
        ("account", "neutrino_comfyui"),
        ("artifact", "venv"),
    ]


def test_the_visual_cpp_dlls_go_beside_python_with_its_own_kept(tmp_path):
    runner, *_ = make(tmp_path, os_name="windows", account="")
    python = os.path.join(runner.module_dir, "python")
    os.makedirs(python)
    open(os.path.join(python, "vcruntime140.dll"), "wb").write(b"own")
    wheel = tmp_path / "vc.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("msvc_runtime-1.data/data/vcruntime140.dll", b"wheel")
        archive.writestr("msvc_runtime-1.data/data/msvcp140.dll", b"msvcp")
        archive.writestr("msvc_runtime-1.data/data/Scripts/msvcp140.dll", b"other")
        archive.writestr("msvc_runtime.pyd", b"x")
    artifact = recipe(is_windows=True)["params"]["artifacts"][3]
    runner.install_artifact(recipe(is_windows=True), artifact, str(wheel))
    assert sorted(os.listdir(python)) == ["msvcp140.dll", "vcruntime140.dll"]
    assert open(os.path.join(python, "vcruntime140.dll"), "rb").read() == b"own"
    assert open(os.path.join(python, "msvcp140.dll"), "rb").read() == b"msvcp"


def test_the_configure_writes_everything_and_waits_for_the_server(tmp_path):
    runner, applier, wiring, idle, _ = make(tmp_path)
    runner.apply(CONFIG)
    assert ("access", "anna") in applier.calls
    assert wiring.calls[0][1]["account"] == "anna"
    assert wiring.calls[0][1]["tools"] == ["codex"]
    _apply, server, is_started = [call for call in applier.calls if call[0] == "apply"][
        0
    ]
    assert is_started and server.is_cpu and server.port == 15000
    assert server.index_url == "https://pypi.org/simple"
    record = runner._record()
    assert record["port"] == 8188 and record["upstream_port"] == 15000
    assert wiring.calls[0][1]["port"] == 15000
    assert idle.calls[-1] == ("take", 15000, 1800)
    assert runner.forwarder_ports() == (8188,)
    assert runner.details(recipe()) == {
        "is_running": True,
        "port": 8188,
        "version": "0.46.0",
    }


def test_a_server_that_never_answers_fails_after_300_seconds(tmp_path):
    runner, *_ = make(tmp_path, stats=False)
    with pytest.raises(ModuleApplyError) as caught:
        runner.apply(CONFIG)
    assert caught.value.code == "apply_failed"
    assert "127.0.0.1:15000" in caught.value.params["detail"]


def test_a_new_first_pypi_source_alone_keeps_the_service(tmp_path):
    runner, applier, *_ = make(tmp_path)
    runner.apply(CONFIG)
    runner.take_source_sets(
        {
            **SETS,
            "pypi": {"probe": "/numpy/", "sources": ["https://mirror.example/simple"]},
        }
    )
    runner.apply(CONFIG)
    servers = [call[1] for call in applier.calls if call[0] == "apply"]
    assert servers[-1].index_url == "https://pypi.org/simple"
    runner.apply({**CONFIG, "torch_build": "nvidia"})
    servers = [call[1] for call in applier.calls if call[0] == "apply"]
    assert servers[-1].index_url == "https://mirror.example/simple"


def test_no_account_reaches_the_folders_or_names_comfy_mcp_without_a_default(tmp_path):
    runner, applier, wiring, *_ = make(tmp_path)
    runner.apply({**CONFIG, "account": ""})
    assert ("access", "") in applier.calls
    assert wiring.calls == []


def test_a_stopped_configure_starts_nothing(tmp_path):
    runner, applier, wiring, idle, _ = make(tmp_path)
    steps = runner.configure_steps(
        CONFIG,
        "stopped",
        [ModuleStep(name="configure", run=None), ModuleStep(name="stop", run=None)],
    )
    steps[0].run(None)
    assert [call[2] for call in applier.calls if call[0] == "apply"] == [False]
    assert runner.forwarder_ports() == ()


def test_the_uninstall_keeps_data_and_takes_the_software_and_the_entries(tmp_path):
    runner, applier, wiring, idle, _ = make(tmp_path)
    runner.apply(CONFIG)
    runner.uninstall(recipe())
    assert ("remove", {"account": "anna", "password": ""}) in wiring.calls
    assert "uninstall" in applier.calls
    removed = [
        call[1]
        for call in applier.calls
        if isinstance(call, tuple) and call[0] == "remove"
    ]
    assert sorted(os.path.basename(path) for path in removed) == [
        "pycache",
        "tmp",
        "uv_cache",
        "venv",
    ]
    assert all("data" != os.path.basename(path) for path in removed)
    assert runner.step_locks("uninstall") and runner.step_locks("account")


def test_a_default_account_the_machine_lacks_is_refused(tmp_path):
    runner, applier, *_ = make(tmp_path)
    with pytest.raises(ModuleApplyError) as caught:
        runner.validate({**CONFIG, "account": "ghost"})
    assert caught.value.code == "account_unknown"
    assert caught.value.params == {"account": "ghost"}
    with pytest.raises(ModuleApplyError):
        runner.apply({**CONFIG, "account": "ghost"})
    assert not [call for call in applier.calls if call[0] == "apply"]
