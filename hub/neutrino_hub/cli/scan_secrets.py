"""Check what is about to be committed for credentials and identifying details.

Run it the way `black --check` is run, before every commit:

    python scripts/scan_secrets/main.py              # everything git would commit
    python scripts/scan_secrets/main.py --staged     # only what is staged
    python scripts/scan_secrets/main.py --history    # every commit reachable now

It reads what git would carry — tracked files plus untracked ones that are not
ignored — so a real `config/` file that is correctly ignored is never opened,
and one that has slipped past `.gitignore` is.

The rules here know this repository; they do not know every vendor's key
format. So `detect-secrets` and `gitleaks` are run too when either is
installed, and their findings are filtered through the same placeholder and
`scan: allow` rules before being shown. Neither is required — a machine
without them still gets the checks that matter most here.

Exit status is 0 when nothing was found and 1 otherwise, so it can gate a
commit. A line that has been looked at and is fine carries `scan: allow`.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from neutrino_hub.utils.secret_scan import (
    SecretFinding,
    SecretScanner,
    is_scannable,
    is_worth_reporting,
)

# How a finding is printed: path, line, rule, then the abbreviated match.
FINDING_FORMAT = "{path}:{line_number}: [{rule}] {detail}"

# Long enough for either tool to walk this tree, short enough that a hung
# one does not hold up a commit.
VENDOR_TIMEOUT_S = 300

EXIT_CLEAN = 0
EXIT_FOUND = 1


def main() -> int:
    """Scan and report.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--staged",
        action="store_true",
        help="only files staged for the next commit",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="every blob in every reachable commit, not the working tree",
    )
    parser.add_argument(
        "--no-entropy",
        action="store_true",
        help="skip the high-entropy rule, which is the noisiest",
    )
    parser.add_argument(
        "--no-vendor",
        action="store_true",
        help="skip detect-secrets and gitleaks even when installed",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print findings only, no summary",
    )
    arguments = parser.parse_args()

    scanner = SecretScanner(is_entropy_checked=not arguments.no_entropy)
    if arguments.history:
        findings = _scan_history(scanner)
        scope = "every reachable commit"
    else:
        paths = _staged_paths() if arguments.staged else _committable_paths()
        findings = _scan_paths(scanner, paths)
        if not arguments.no_vendor:
            findings += _scan_with_vendors(paths)
        scope = f"{len(paths)} files"

    for finding in findings:
        print(
            FINDING_FORMAT.format(
                path=finding.path,
                line_number=finding.line_number,
                rule=finding.rule,
                detail=finding.detail,
            )
        )
    if arguments.quiet:
        return EXIT_FOUND if findings else EXIT_CLEAN

    if findings:
        print(f"\n{len(findings)} to look at across {scope}.", file=sys.stderr)
        print(
            "Each one is either real and must go, or safe and gets "
            f"`{'scan: allow'}` on its line.",
            file=sys.stderr,
        )
        return EXIT_FOUND
    print(f"Nothing to answer for across {scope}.", file=sys.stderr)
    return EXIT_CLEAN


def _committable_paths() -> list:
    """Everything git would put in a commit: tracked, plus untracked-not-ignored."""
    tracked = _git(["ls-files", "--cached", "--others", "--exclude-standard"])
    return [path for path in tracked.splitlines() if path and is_scannable(path)]


def _staged_paths() -> list:
    """The files staged for the next commit."""
    staged = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [path for path in staged.splitlines() if path and is_scannable(path)]


def _scan_paths(scanner: SecretScanner, paths: list) -> list:
    """Scan each path, skipping what cannot be read as text."""
    findings = []
    for path in paths:
        try:
            with open(Path(_repo_root()) / path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        findings += scanner.scan_text(text, path=path)
    return findings


def _scan_history(scanner: SecretScanner) -> list:
    """Scan every blob in every reachable commit, and every commit message.

    Slower than the working tree by far, and the only way to answer "is this
    history safe to publish" — a value deleted in a later commit is still in
    the one that added it.
    """
    findings = _scan_messages(scanner)
    listing = _git(["rev-list", "--objects", "--all"])
    seen = set()
    for entry in listing.splitlines():
        parts = entry.split(" ", 1)
        if len(parts) != 2:
            continue
        blob, path = parts
        if blob in seen or not is_scannable(path):
            continue
        seen.add(blob)
        kind = _git(["cat-file", "-t", blob]).strip()
        if kind != "blob":
            continue
        try:
            text = _git(["cat-file", "blob", blob])
        except UnicodeDecodeError:
            continue
        findings += scanner.scan_text(text, path=f"{blob[:8]} {path}")
    return findings


def _scan_messages(scanner: SecretScanner) -> list:
    """Scan the commit messages, which no file-based scan would ever read."""
    messages = _git(["log", "--all", "--format=%H%x00%B%x00"])
    findings = []
    for record in messages.split("\x00\x00"):
        if "\x00" not in record:
            continue
        commit, body = record.strip().split("\x00", 1)
        findings += scanner.scan_text(body, path=f"commit {commit[:8]}")
    return findings


def _scan_with_vendors(paths: list) -> list:
    """Run whichever general-purpose scanners this machine has.

    Their findings are filtered through this repository's own idea of a
    placeholder, so an example file full of `replace-me` does not drown the
    one line that matters.

    Args:
        paths: The files to hand them.

    Returns:
        Findings from every tool that was available.
    """
    findings = []
    for run in (_run_detect_secrets, _run_gitleaks):
        findings += run(paths)
    return findings


def _run_detect_secrets(paths: list) -> list:
    """Findings from detect-secrets, when it is installed."""
    binary = _find_tool("detect-secrets")
    if binary is None:
        return []
    try:
        result = subprocess.run(
            [binary, "scan"] + paths,
            capture_output=True,
            text=True,
            timeout=VENDOR_TIMEOUT_S,
        )
        report = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    findings = []
    for path, entries in report.get("results", {}).items():
        for entry in entries:
            number = entry.get("line_number", 0)
            line = _read_line(path, number)
            if not is_worth_reporting(line, following=_read_line(path, number + 1)):
                continue
            findings.append(
                SecretFinding(
                    path,
                    number,
                    f"detect-secrets/{_slug(entry.get('type', 'unknown'))}",
                    entry.get("type", "unknown"),
                    line.strip()[:200],
                )
            )
    return findings


def _run_gitleaks(paths: list) -> list:
    """Findings from gitleaks, when it is installed.

    Gitleaks scans a directory rather than a list of files, so the whole tree
    is handed to it and anything outside what git would commit is dropped
    afterwards.
    """
    binary = _find_tool("gitleaks")
    if binary is None:
        return []
    wanted = set(paths)
    with tempfile.NamedTemporaryFile(suffix=".json") as report_file:
        try:
            subprocess.run(
                [
                    binary,
                    "dir",
                    ".",
                    "--no-banner",
                    "--report-format",
                    "json",
                    "--report-path",
                    report_file.name,
                ],
                capture_output=True,
                text=True,
                timeout=VENDOR_TIMEOUT_S,
            )
            report = json.loads(Path(report_file.name).read_text() or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return []

    findings = []
    for entry in report or []:
        path = entry.get("File", "").lstrip("./")
        if path not in wanted:
            continue
        number = entry.get("StartLine", 0)
        line = _read_line(path, number)
        if not is_worth_reporting(line, following=_read_line(path, number + 1)):
            continue
        findings.append(
            SecretFinding(
                path,
                number,
                f"gitleaks/{_slug(entry.get('RuleID', 'unknown'))}",
                entry.get("Description", entry.get("RuleID", "unknown"))[:60],
                line.strip()[:200],
            )
        )
    return findings


def _find_tool(name: str) -> "str | None":
    """Locate a scanner on the path or beside the running interpreter.

    A virtualenv's scripts are usually not on the path of the shell that runs
    this, so a tool installed with the project's own dev dependencies would
    otherwise look absent and be skipped in silence.

    Args:
        name: The command to look for.

    Returns:
        A path to run, or None.
    """
    found = shutil.which(name)
    if found:
        return found
    beside = Path(sys.executable).parent / name
    return str(beside) if beside.exists() else None


def _read_line(path: str, number: int) -> str:
    """One line of a file, empty when it cannot be read."""
    try:
        with open(
            Path(_repo_root()) / path, encoding="utf-8", errors="replace"
        ) as handle:
            for index, line in enumerate(handle, start=1):
                if index == number:
                    return line.rstrip("\n")
    except OSError:
        return ""
    return ""


def _slug(value: str) -> str:
    """A rule name in the same shape as this scanner's own."""
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def _repo_root() -> str:
    """The working copy's top level.

    Every git command runs from here. Without it, running the scan from a
    subdirectory silently narrows it to that subdirectory, which is how a
    check that gates commits would come back clean on a repository it had
    only half read.

    Returns:
        An absolute path, or the current directory outside a working copy.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return result.stdout.strip() if result.returncode == 0 else "."


def _git(arguments: list) -> str:
    """Run a git command at the repository root and return its output.

    Args:
        arguments: Arguments after ``git``.

    Returns:
        Standard output, empty when the command failed.
    """
    result = subprocess.run(
        ["git", "-C", _repo_root()] + arguments,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


if __name__ == "__main__":
    sys.exit(main())
