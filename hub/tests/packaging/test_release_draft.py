"""The ``draft`` job of ``.github/workflows/release.yml``.

The job collects every file the build jobs made, then writes each edition's
site apart with ``build_checksums.py``. What is asserted is the collection
step run under bash over stand-in artifacts, the draft opened from the intl
site's files alone, and the cn site's files written inside the mainland tree
into the artifact ``publish_cn.py`` reads.
"""

import importlib.util
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
PUBLISH = REPO_ROOT / "packaging" / "ci" / "publish_cn.py"
CHECKSUMS = "python3 packaging/build/build_checksums.py"


def draft_steps() -> list:
    """The steps of the release workflow's draft job."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["draft"]["steps"]


def step_named(name: str) -> dict:
    (step,) = [step for step in draft_steps() if step.get("name") == name]
    return step


def checksum_steps() -> dict:
    """The two steps that write a site, by the edition each names."""
    steps = {}
    for step in draft_steps():
        command = " ".join(str(step.get("run", "")).split())
        if command.startswith(CHECKSUMS):
            words = shlex.split(command)
            edition = (
                words[words.index("--edition") + 1] if "--edition" in words else "intl"
            )
            steps[edition] = (step, words)
    return steps


def upload_paths() -> dict:
    """Each artifact the job uploads, by its name, to the path it takes."""
    return {
        step["with"]["name"]: step["with"]["path"]
        for step in draft_steps()
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    }


def test_the_collection_takes_every_job_s_files_but_checks_and_go_programs(
    tmp_path,
):
    artifacts = {
        "hub_amd64": ["neutrino-hub_9.9.9_amd64.deb"],
        "cn_hub_amd64": ["neutrino-hub_9.9.9_amd64-cn.deb"],
        "sources": ["neutrino-9.9.9-source.tar.xz", "install.sh"],
        "cn_sources": ["neutrino-9.9.9-cn-source.tar.xz", "install-cn.sh"],
        "check_client_windows_x64_install": ["check.log"],
        "go_linux-amd64": ["neutrino_transport"],
    }
    for artifact, names in artifacts.items():
        (tmp_path / "artifacts" / artifact).mkdir(parents=True)
        for name in names:
            (tmp_path / "artifacts" / artifact / name).write_text(name)

    finished = subprocess.run(
        [shutil.which("bash"), "--noprofile", "--norc", "-eo", "pipefail", "-c"]
        + [step_named("Collect the files of both editions")["run"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert finished.returncode == 0, finished.stderr
    assert sorted(path.name for path in (tmp_path / "collected").iterdir()) == [
        "install-cn.sh",
        "install.sh",
        "neutrino-9.9.9-cn-source.tar.xz",
        "neutrino-9.9.9-source.tar.xz",
        "neutrino-hub_9.9.9_amd64-cn.deb",
        "neutrino-hub_9.9.9_amd64.deb",
    ]


def test_the_cc_switch_files_join_the_collection_before_either_site():
    steps = [" ".join(str(step.get("run", "")).split()) for step in draft_steps()]
    cc_switch = steps.index(
        "python3 packaging/build/build_cc_switch.py --output-dir collected"
    )

    assert all(
        cc_switch < index
        for index, command in enumerate(steps)
        if command.startswith(CHECKSUMS)
    )


def test_the_intl_site_is_written_from_the_collection_into_dist():
    step, words = checksum_steps()["intl"]

    assert "working-directory" not in step
    assert words[words.index("--release-files") + 1] == "collected"
    assert words[words.index("--output-dir") + 1] == "dist"


def test_the_draft_is_opened_from_the_intl_site_s_files_alone():
    command = step_named("Open the draft release")["run"].split()

    assert "gh" in command and "create" in command
    assert command[-1] == "dist/*"
    assert not any("dist_cn" in word or "collected" in word for word in command)
    assert upload_paths()["release_dist"] == "dist/*"


def test_the_cn_site_is_written_inside_the_mainland_tree_into_its_own_artifact():
    step, words = checksum_steps()["cn"]
    unpack = step_named("Unpack the mainland source tree")

    assert step["working-directory"] == "cn"
    assert "-C cn" in unpack["run"] and "collected/*-cn-source.tar.xz" in unpack["run"]
    assert draft_steps().index(unpack) < draft_steps().index(step)
    assert words[words.index("--release-files") + 1] == "$GITHUB_WORKSPACE/collected"
    assert words[words.index("--output-dir") + 1] == "$GITHUB_WORKSPACE/dist_cn"
    assert upload_paths()["release_dist_cn"] == "dist_cn/*"


def test_publish_cn_reads_the_artifact_the_draft_job_uploads_the_cn_site_in():
    spec = importlib.util.spec_from_file_location("publish_cn", PUBLISH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert upload_paths()[module.PUBLISH_ARTIFACT] == "dist_cn/*"
