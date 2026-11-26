"""A Python environment from a lock: its parts, its sources, the uv commands it runs.

What these pin: a lock splits into one part per ``# from`` index with every
comment left out; an index belongs to the set whose source holds it, with
its path below that source; the environment is made with no seed; each part
installs with ``--require-hashes --no-deps --index-url`` from its set's
first ranked source with the index's path, the artifact's sets first in
their order, and the next ranked source after a failure; ``uv pip check``
follows the parts; no ``uv pip sync`` ever runs; uv as root installs wheels
alone with ``--no-build``; a custom node's requirements install with no
hash.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.python_env import (
    PythonEnvironment,
    environment_python,
    index_source,
    lock_parts,
    uv_variables,
)

LOCK = """\
numpy==2.5.5 \\
    --hash=sha256:aaaa \\
    --hash=sha256:bbbb
    # via torch
    # from https://pypi.org/simple
torch==2.15.0+cpu \\
    --hash=sha256:cccc
    # via -r venv.in
    # from https://download.pytorch.org/whl/cpu
pip==26.3 \\
    --hash=sha256:dddd
    # from https://pypi.org/simple
"""
SETS = {
    "pypi": {
        "sources": ["https://pypi.org/simple", "https://mirror.example/pypi/simple"]
    },
    "pytorch": {
        "sources": [
            "https://download.pytorch.org/whl",
            "https://mirror.example/pytorch",
        ]
    },
}


def test_a_lock_splits_by_its_index_with_its_hashes_and_no_comment():
    parts = lock_parts(LOCK)
    assert [index for index, _part in parts] == [
        "https://pypi.org/simple",
        "https://download.pytorch.org/whl/cpu",
    ]
    pypi = parts[0][1]
    assert "numpy==2.5.5" in pypi and "pip==26.3" in pypi
    assert "--hash=sha256:aaaa" in pypi and "#" not in pypi
    assert "torch==2.15.0+cpu" in parts[1][1]


def test_an_entry_with_no_index_is_refused():
    with pytest.raises(ModuleApplyError) as caught:
        lock_parts("numpy==1 \\\n    --hash=sha256:aa\n")
    assert caught.value.code == "install_failed"


def test_an_index_belongs_to_the_set_whose_source_holds_it():
    assert index_source("https://download.pytorch.org/whl/cu132", SETS) == (
        "pytorch",
        "/cu132",
    )
    assert index_source("https://pypi.org/simple", SETS) == ("pypi", "")
    with pytest.raises(ModuleApplyError):
        index_source("https://other.example/simple", SETS)


def test_uv_takes_no_python_and_no_configuration_and_a_stack_on_windows():
    assert uv_variables(cache_dir="/c", os_name="linux") == {
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_CONFIG": "1",
        "UV_CACHE_DIR": "/c",
    }
    assert uv_variables(cache_dir="C:\\c", os_name="windows")["UV_STACK_SIZE"] == (
        "16777216"
    )
    assert (
        environment_python("C:\\d\\venv", "windows")
        == "C:\\d\\venv\\Scripts\\python.exe"
    )
    assert environment_python("/d/venv", "linux") == "/d/venv/bin/python"


class Runs:
    """Records each uv command and answers it; the first install from a failing source fails."""

    def __init__(self, failing=()):
        self.argvs = []
        self.failing = tuple(failing)

    def __call__(self, argv):
        self.argvs.append(list(argv))
        if any(source in " ".join(argv) for source in self.failing):
            return 1, "error: no file of that hash\n"
        return 0, ""


def _environment(runs, ranked, *, is_root=False):
    return PythonEnvironment(
        uv="/m/uv/uv",
        python="/m/python/bin/python3",
        folder="/d/venv",
        os_name="linux",
        run=runs,
        rank=ranked.get,
        log=lambda line: None,
        name="comfyui",
        is_root=is_root,
    )


def test_the_environment_is_made_with_no_seed_and_the_lock_installed_part_by_part(
    tmp_path,
):
    runs = Runs()
    ranked = {
        "pytorch": [
            "https://mirror.example/pytorch",
            "https://download.pytorch.org/whl",
        ],
        "pypi": ["https://pypi.org/simple"],
    }
    environment = _environment(runs, ranked)
    environment.make()
    environment.install(
        LOCK,
        parts_dir=str(tmp_path),
        source_sets=SETS,
        set_order=("pytorch", "pypi"),
    )
    assert runs.argvs[0] == [
        "/m/uv/uv",
        "venv",
        "--python",
        "/m/python/bin/python3",
        "/d/venv",
    ]
    first, second, check = runs.argvs[1:]
    assert first[:8] == [
        "/m/uv/uv",
        "pip",
        "install",
        "--python",
        "/d/venv/bin/python",
        "--require-hashes",
        "--no-deps",
        "--index-url",
    ]
    assert first[8] == "https://mirror.example/pytorch/cpu"
    assert "torch==2.15.0+cpu" in open(first[-1]).read()
    assert second[8] == "https://pypi.org/simple"
    assert check == ["/m/uv/uv", "pip", "check", "--python", "/d/venv/bin/python"]
    assert all("sync" not in argv for argv in runs.argvs)
    assert all("--seed" not in argv for argv in runs.argvs)
    assert all("--no-build" not in argv for argv in runs.argvs)


def test_a_source_that_fails_a_part_hands_it_to_the_next(tmp_path):
    runs = Runs(failing=("mirror.example",))
    ranked = {
        "pytorch": [
            "https://mirror.example/pytorch",
            "https://download.pytorch.org/whl",
        ],
        "pypi": ["https://pypi.org/simple"],
    }
    _environment(runs, ranked).install(
        LOCK, parts_dir=str(tmp_path), source_sets=SETS, set_order=("pytorch", "pypi")
    )
    indexes = [argv[8] for argv in runs.argvs if argv[2] == "install"]
    assert indexes == [
        "https://mirror.example/pytorch/cpu",
        "https://download.pytorch.org/whl/cpu",
        "https://pypi.org/simple",
    ]


def test_no_source_that_serves_a_part_fails_the_install(tmp_path):
    runs = Runs(failing=("pypi.org",))
    with pytest.raises(ModuleApplyError) as caught:
        _environment(
            runs,
            {
                "pypi": ["https://pypi.org/simple"],
                "pytorch": ["https://download.pytorch.org/whl"],
            },
        ).install(LOCK, parts_dir=str(tmp_path), source_sets=SETS)
    assert caught.value.code == "install_failed"
    assert "no file of that hash" in caught.value.params["detail"]


def test_uv_as_root_installs_wheels_alone(tmp_path):
    runs = Runs()
    _environment(
        runs,
        {
            "pypi": ["https://pypi.org/simple"],
            "pytorch": ["https://download.pytorch.org/whl"],
        },
        is_root=True,
    ).install(LOCK, parts_dir=str(tmp_path), source_sets=SETS)
    installs = [argv for argv in runs.argvs if argv[2] == "install"]
    assert installs and all(argv[3] == "--no-build" for argv in installs)


def test_a_custom_nodes_requirements_install_with_no_hash():
    runs = Runs(failing=("broken",))
    environment = _environment(runs, {})
    assert (
        environment.install_requirements(
            "/n/a/requirements.txt", "https://pypi.org/simple"
        )
        == ""
    )
    assert runs.argvs[-1] == [
        "/m/uv/uv",
        "pip",
        "install",
        "--python",
        "/d/venv/bin/python",
        "--index-url",
        "https://pypi.org/simple",
        "-r",
        "/n/a/requirements.txt",
    ]
    assert environment.install_requirements("/n/broken/requirements.txt", "x")
