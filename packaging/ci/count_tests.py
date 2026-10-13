"""Count the tests of every suite and write the tests badge the READMEs show.

    python3 packaging/ci/count_tests.py . docs/guide/public/badges/tests.json

Runs on: any machine whose Python has ``hub[dev]``, ``agent`` and
``client/desktop`` installed. The hub, the agent, the desktop client and the
integration suite are counted by ``pytest --collect-only -q`` in their own
directories, the Android app by the ``@Test`` annotations in its test source
sets; the iOS app is not counted. Unit is every suite but the integration
one. The file is a shields.io endpoint answer.

Not pure: runs pytest, writes the badge file.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# The suites pytest collects, each from its own directory and settings.
COUNT_PYTEST_UNIT_DIRS = {
    "hub": "hub",
    "agent": "agent",
    "client": "client/desktop",
}
COUNT_PYTEST_INTEGRATION_DIR = "packaging/integration"
COUNT_PYTEST_SUMMARY = re.compile(r"^(\d+) tests? collected", re.MULTILINE)
# The Android app's test source sets; a missing one counts nothing.
COUNT_ANDROID_SOURCE_DIR = "client/android/app/src"
COUNT_ANDROID_TEST_SOURCE_SETS = ("test", "test_netbird", "androidTest")
COUNT_ANDROID_TEST_ANNOTATION = re.compile(r"^\s*@Test\b", re.MULTILINE)
# The endpoint answer: https://shields.io/badges/endpoint-badge
COUNT_BADGE_LABEL = "tests"
COUNT_BADGE_COLOR = "22d3ee"


def main() -> int:
    """Count the tests and write the badge file.

    Returns:
        The process exit status.

    Raises:
        SystemExit: When a collection fails or a suite counts no test.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="the repository's root")
    parser.add_argument("output", help="the badge file written")
    arguments = parser.parse_args()
    root = Path(arguments.root).resolve()

    counts = {
        name: count_collected(root / directory)
        for name, directory in COUNT_PYTEST_UNIT_DIRS.items()
    }
    counts["android"] = count_android(root / COUNT_ANDROID_SOURCE_DIR)
    unit = sum(counts.values())
    integration = count_collected(root / COUNT_PYTEST_INTEGRATION_DIR)
    for name, count in counts.items():
        print(f"{name}: {count}", flush=True)
    print(f"unit: {unit}", flush=True)
    print(f"integration: {integration}", flush=True)

    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(badge(unit, integration), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output}", flush=True)
    return 0


def count_collected(directory: Path) -> int:
    """Count the tests pytest collects in one directory.

    Args:
        directory: The suite's directory, where its pytest settings are.

    Returns:
        The number of tests collected.

    Raises:
        SystemExit: When the collection fails or prints no count.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"collecting {directory} exited {result.returncode}:\n"
            f"{(result.stdout + result.stderr)[-4000:]}"
        )
    found = COUNT_PYTEST_SUMMARY.search(result.stdout)
    if found is None:
        raise SystemExit(f"collecting {directory} printed no count")
    return int(found.group(1))


def count_android(source_dir: Path) -> int:
    """Count the ``@Test`` annotations in the Android app's test source sets.

    Args:
        source_dir: The app's ``src`` directory.

    Returns:
        The number of annotations.

    Raises:
        SystemExit: When no source set holds a test.
    """
    count = 0
    for source_set in COUNT_ANDROID_TEST_SOURCE_SETS:
        directory = source_dir / source_set
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.kt")):
            text = path.read_text(encoding="utf-8")
            count += len(COUNT_ANDROID_TEST_ANNOTATION.findall(text))
    if count == 0:
        raise SystemExit(f"no Android test under {source_dir}")
    return count


def badge(unit: int, integration: int) -> dict:
    """Build the shields.io endpoint answer.

    Args:
        unit: The unit tests of every suite but the integration one.
        integration: The integration tests.

    Returns:
        The answer, ready to write as JSON.
    """
    return {
        "schemaVersion": 1,
        "label": COUNT_BADGE_LABEL,
        "message": f"{unit} unit · {integration} integration",
        "color": COUNT_BADGE_COLOR,
    }


if __name__ == "__main__":
    sys.exit(main())
