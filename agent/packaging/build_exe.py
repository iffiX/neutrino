"""Build the agent's Windows installer.

    python agent/packaging/build_exe.py --output-dir dist/

The installer carries its own Python. Windows ships none, and the agent is
meant to land on a machine nobody has prepared, so the interpreter is
python.org's embeddable package — the standard library and nothing else, no
pip and no installer of its own — pinned by hash below.

The agent runs from a scheduled task rather than a Windows service. A service
has to answer the service control manager within seconds of starting, which a
plain Python process cannot do without a wrapper binary, and the agent carries
no dependencies on any platform.

Needs Inno Setup's ISCC.exe, which the GitHub Windows runner image carries.

Not pure: downloads an interpreter, writes a package tree, runs ISCC.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_ROOT.parent
PACKAGE_NAME = "neutrino-agent"

# The interpreter the installer carries. Pinned by hash: this is the one
# third-party artifact the build fetches, and a package that installs an
# unverified interpreter as SYSTEM is not one to ship.
PYTHON_VERSION = "3.13.7"
PYTHON_URL = (
    "https://www.python.org/ftp/python/"
    f"{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
)
PYTHON_SHA256 = (
    "f6cca216a359be84797cabb54149ce5e062afb16cc7567eb7fc51cacb2d86b65"  # scan: allow
)

# What the scheduled task is called, and what the uninstaller looks for.
TASK_NAME = "Neutrino Agent"

# Where ISCC lives when it is not on the path.
ISCC_CANDIDATES = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)

CONSOLE_WRAPPER = """@echo off
rem Run the agent in a terminal, for `nagent --once` and for reading errors.
"%~dp0python\\python.exe" -m neutrino_agent.cli %*
"""

SERVICE_WRAPPER = """@echo off
rem What the scheduled task starts. pythonw so no console window is created
rem for a process that nobody is watching.
"%~dp0python\\pythonw.exe" -m neutrino_agent.cli
"""

# @NAME@ rather than str.format: an Inno script is mostly braces already.
# Single quotes around it because the script itself is full of doubled ones,
# which is how Inno spells a quote inside a quoted value.
INNO_SCRIPT = r'''[Setup]
AppId={{A7E3C1D2-5B84-4F16-9C0A-2E7D8B3F6A15}
AppName=Neutrino Agent
AppVersion=@VERSION@
AppPublisher=@PUBLISHER@
AppPublisherURL=https://github.com/iffiX/neutrino
DefaultDirName={autopf}\Neutrino Agent
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=@LICENSE@
OutputDir=@OUTPUT_DIR@
OutputBaseFilename=@BASENAME@
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "@PAYLOAD@\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Register-ScheduledTask -TaskName '@TASK_NAME@' -Force -Action (New-ScheduledTaskAction -Execute '{app}\nagent_service.cmd') -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal (New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest)"""; Flags: runhidden; StatusMsg: "Registering the agent's startup task"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Start-ScheduledTask -TaskName '@TASK_NAME@'"""; Flags: runhidden; StatusMsg: "Starting the agent"

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Stop-ScheduledTask -TaskName '@TASK_NAME@' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName '@TASK_NAME@' -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden; RunOnceId: "RemoveAgentTask"
'''


def main() -> int:
    """Build the installer.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .exe")
    parser.add_argument(
        "--publisher",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the AppPublisher field",
    )
    arguments = parser.parse_args()

    version = _version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = f"{PACKAGE_NAME}-{version}-setup"

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        payload = root / "payload"
        _lay_out(payload, root / "python-embed.zip", version)

        script = root / "neutrino_agent.iss"
        script.write_text(
            INNO_SCRIPT.replace("@VERSION@", version)
            .replace("@PUBLISHER@", arguments.publisher)
            .replace("@LICENSE@", str(REPO_ROOT / "LICENSE"))
            .replace("@OUTPUT_DIR@", str(output_dir))
            .replace("@BASENAME@", basename)
            .replace("@PAYLOAD@", str(payload))
            .replace("@TASK_NAME@", TASK_NAME),
            encoding="utf-8",
        )
        _build(script)

    target = output_dir / f"{basename}.exe"
    if not target.is_file():
        raise SystemExit(f"ISCC wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(payload: Path, archive: Path, version: str) -> None:
    """Write everything the installer carries.

    Args:
        payload: The directory standing in for the install directory.
        archive: Where to keep the downloaded interpreter.
        version: The version being packaged.
    """
    python_dir = payload / "python"
    python_dir.mkdir(parents=True)
    _fetch_python(archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(python_dir)
    _open_import_path(python_dir)

    package_dir = payload / "neutrino_agent"
    shutil.copytree(
        AGENT_ROOT / "neutrino_agent",
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build_package.py"),
    )
    # No .dist-info reaches a machine installed this way either, so the
    # version is stamped the way the other packages' builds do it.
    (package_dir / "_version.py").write_text(
        f'"""Written by the packaging build. Do not edit."""\n\n'
        f'AGENT_VERSION = "{version}"\n',
        encoding="utf-8",
    )

    (payload / "nagent.cmd").write_text(CONSOLE_WRAPPER, encoding="utf-8")
    (payload / "nagent_service.cmd").write_text(SERVICE_WRAPPER, encoding="utf-8")


def _fetch_python(archive: Path) -> None:
    """Download the embeddable interpreter and check it against its hash.

    Args:
        archive: Where to write the zip.

    Raises:
        SystemExit: If what arrived is not what was pinned.
    """
    print(f"fetching {PYTHON_URL}")
    with urllib.request.urlopen(PYTHON_URL, timeout=120) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != PYTHON_SHA256:
        raise SystemExit(
            f"the interpreter at {PYTHON_URL} hashes to {digest}, "
            f"not the pinned {PYTHON_SHA256}"
        )
    archive.write_bytes(payload)


def _open_import_path(python_dir: Path) -> None:
    """Let the bundled interpreter see the directory above it.

    The embeddable package resolves imports from its ``._pth`` file alone and
    ignores PYTHONPATH, so the agent beside it is invisible until the file
    says otherwise.

    Args:
        python_dir: The extracted interpreter.

    Raises:
        SystemExit: If the file is not the shape this expects.
    """
    try:
        path_file = next(python_dir.glob("python*._pth"))
    except StopIteration:
        raise SystemExit("the embeddable package carries no ._pth file")
    lines = path_file.read_text(encoding="utf-8").splitlines()
    if "." not in lines:
        raise SystemExit(f"no '.' entry in {path_file.name} to add '..' beside")
    lines.insert(lines.index(".") + 1, "..")
    path_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build(script: Path) -> None:
    """Run ISCC over the generated script.

    Args:
        script: The .iss to compile.

    Raises:
        SystemExit: If Inno Setup is not installed, or refuses the script.
    """
    iscc = shutil.which("ISCC") or next(
        (path for path in ISCC_CANDIDATES if Path(path).is_file()), None
    )
    if iscc is None:
        raise SystemExit(
            "Inno Setup's ISCC.exe is needed to build the Windows installer"
        )
    result = subprocess.run([iscc, str(script)], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit((result.stdout or result.stderr).strip())


def _version() -> str:
    """The version declared in the agent's pyproject."""
    for line in (
        (AGENT_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in agent/pyproject.toml")


if __name__ == "__main__":
    raise SystemExit(main())
