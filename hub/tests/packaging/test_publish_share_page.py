"""The ``share_page`` job of ``.github/workflows/publish.yml``.

The job's deploy step runs under bash as GitHub runs it, with stand-ins for
``python3`` and ``npx`` on its ``PATH`` that record their arguments. What is
asserted is the tag's tree checked out after the ``publish`` job, the build
and the deploy to ``neutrinohub-share``, and a pre-release or a missing
secret deploying nothing while the step succeeds.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish.yml"
TAG = "v9.9.9"
# Stand-ins for the two repository secrets.
SECRETS = {
    "CLOUDFLARE_API_TOKEN": "fake-token-0123",
    "CLOUDFLARE_ACCOUNT_ID": "fake-account-0123",
}
# The commands the step runs for a release's tag, in order.
BUILD = "python3 packaging/build/build_share_page.py --output-dir dist/share_page"
DEPLOY = (
    "npx --yes wrangler@4.150.0 pages deploy dist/share_page"
    " --project-name neutrinohub-share --branch main"
)


def share_page_job() -> dict:
    """The ``share_page`` job of the publish workflow."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["share_page"]


def deploy_step() -> dict:
    """The step of the job that builds and deploys the page."""
    (step,) = [step for step in share_page_job()["steps"] if "run" in step]
    return step


def run_deploy(tmp_path: Path, environment: dict, npx_exit: int = 0) -> tuple:
    """Run the deploy step's script with stand-ins for python3 and npx.

    Returns:
        The finished process, and each command the stand-ins ran, as one line
        of its name and arguments.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, status in (("python3", 0), ("npx", npx_exit)):
        stand_in = bin_dir / name
        stand_in.write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "{name} $*" >> "$CALLS"\nexit {status}\n'
        )
        stand_in.chmod(0o755)
    script = tmp_path / "deploy.sh"
    script.write_text(deploy_step()["run"])
    calls = tmp_path / "calls"
    finished = subprocess.run(
        [shutil.which("bash"), "--noprofile", "--norc", "-eo", "pipefail", script],
        cwd=tmp_path,
        env={"PATH": str(bin_dir), "CALLS": str(calls), **environment},
        capture_output=True,
        text=True,
        check=False,
    )
    ran = calls.read_text().splitlines() if calls.exists() else []
    return finished, ran


def test_the_job_checks_out_the_tag_after_the_publish_job():
    job = share_page_job()
    (checkout,) = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]

    assert job["needs"] == "publish"
    assert checkout["with"]["ref"] == "${{ inputs.tag }}"
    assert job["permissions"] == {"contents": "read"}


def test_the_step_reads_the_tag_and_the_two_repository_secrets():
    step = deploy_step()

    assert step["env"] == {
        "TAG": "${{ inputs.tag }}",
        "CLOUDFLARE_API_TOKEN": "${{ secrets.CLOUDFLARE_API_TOKEN }}",
        "CLOUDFLARE_ACCOUNT_ID": "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}",
    }
    assert "${{" not in step["run"]


def test_node_meets_the_pinned_wrangler():
    (node,) = [
        step
        for step in share_page_job()["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    ]

    assert int(node["with"]["node-version"]) >= 22


def test_a_release_tag_builds_the_page_and_deploys_it_to_the_project(tmp_path):
    finished, ran = run_deploy(tmp_path, {"TAG": TAG, **SECRETS})

    assert finished.returncode == 0, finished.stderr
    assert ran == [BUILD, DEPLOY]


def test_a_failed_deploy_fails_the_step(tmp_path):
    finished, ran = run_deploy(tmp_path, {"TAG": TAG, **SECRETS}, npx_exit=1)

    assert finished.returncode == 1
    assert ran == [BUILD, DEPLOY]


@pytest.mark.parametrize("tag", ["v9.9.9-rc1", "v9.9.9-beta.2", "v9.9.9-lab"])
def test_a_pre_release_deploys_nothing(tmp_path, tag):
    finished, ran = run_deploy(tmp_path, {"TAG": tag, **SECRETS})

    assert finished.returncode == 0, finished.stderr
    assert ran == []
    assert finished.stdout == f"{tag} is a pre-release; no share page is deployed\n"


@pytest.mark.parametrize("missing", sorted(SECRETS))
def test_a_missing_secret_deploys_nothing_and_succeeds(tmp_path, missing):
    present = {name: value for name, value in SECRETS.items() if name != missing}
    finished, ran = run_deploy(tmp_path, {"TAG": TAG, missing: "", **present})

    assert finished.returncode == 0, finished.stderr
    assert ran == []
    assert finished.stdout == (
        f"::warning::{missing} is not set; no share page is deployed\n"
    )
