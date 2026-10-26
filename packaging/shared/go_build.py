"""The Go builds every package shares: the pinned toolchain, the five targets,
one static binary per target with the version stamped, and the gomobile pin
read off ``transport/go.mod``.

``build_transport.py`` and ``build_ssh_server.py`` call :func:`build_program`
for one module each; ``build_core_transport.py`` and ``build_core_netbird.py``
call :func:`gomobile_version` and :func:`install_gomobile` for the phones'
libraries.

Not pure: runs the Go toolchain and reads the tree.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from shared.constants import PACKAGING_GO_TARGETS, PACKAGING_GO_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]

# Where every package build takes the Go programs of its target from.
GO_PROGRAMS_DIR = Path("dist") / "go"
# The gomobile tools, installed once per pinned version under the cache.
GO_TOOLS_DIR = Path.home() / ".cache" / "neutrino" / "go_tools"
GO_MOBILE_MODULE = "golang.org/x/mobile"


def target_parts(target: str) -> tuple[str, str, str]:
    """Split a target into GOOS, GOARCH and the binary's extension.

    Args:
        target: One of :data:`PACKAGING_GO_TARGETS`, ``linux-amd64`` and the like.

    Returns:
        ``(goos, goarch, extension)``, the extension ``.exe`` on Windows.

    Raises:
        SystemExit: When the target is not one the release builds.
    """
    if target not in PACKAGING_GO_TARGETS:
        raise SystemExit(
            f"target {target!r} is not one of {', '.join(PACKAGING_GO_TARGETS)}"
        )
    goos, goarch = target.split("-")
    return goos, goarch, ".exe" if goos == "windows" else ""


def require_go() -> str:
    """The ``go`` program on the path, at the pinned version.

    Returns:
        The path of ``go``.

    Raises:
        SystemExit: When ``go`` is missing or another version.
    """
    program = shutil.which("go")
    if program is None:
        raise SystemExit(f"go {PACKAGING_GO_VERSION} is needed and is not on the path")
    text = subprocess.run(
        [program, "version"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"go(\d+\.\d+(?:\.\d+)?)", text)
    if match is None or match.group(1) != PACKAGING_GO_VERSION:
        raise SystemExit(f"go {PACKAGING_GO_VERSION} is needed, found {text.strip()!r}")
    return program


def package_version() -> str:
    """The version the packages declare, read off the hub's pyproject.

    Returns:
        The version, ``0.6.0`` and the like.

    Raises:
        SystemExit: When the pyproject declares none.
    """
    text = (REPO_ROOT / "hub" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("hub/pyproject.toml declares no version")
    return match.group(1)


def build_program(
    module_dir: Path, package: str, name: str, target: str, output_dir: Path
) -> Path:
    """Cross-compile one static Go program with the version stamped.

    Args:
        module_dir: The module's directory, ``transport`` or ``agent/sshserver``.
        package: The main package inside it, ``./cmd/neutrino_transport``.
        name: The binary's name without an extension.
        target: One of :data:`PACKAGING_GO_TARGETS`.
        output_dir: The build's output directory; the binary lands in
            ``<output_dir>/go/<target>/``.

    Returns:
        The binary written.

    Raises:
        SystemExit: When the toolchain is missing or the build fails.
    """
    program = require_go()
    goos, goarch, extension = target_parts(target)
    destination = output_dir / "go" / target / f"{name}{extension}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(
        os.environ,
        CGO_ENABLED="0",
        GOOS=goos,
        GOARCH=goarch,
        GOTOOLCHAIN="local",
        GOFLAGS="-mod=mod",
    )
    command = [
        program,
        "build",
        "-trimpath",
        "-ldflags",
        f"-s -w -X main.version={package_version()}",
        "-o",
        str(destination.resolve()),
        package,
    ]
    print(" ".join(command))
    result = subprocess.run(command, cwd=module_dir, env=environment, check=False)
    if result.returncode != 0:
        raise SystemExit(f"go build of {name} for {target} exited {result.returncode}")
    return destination


def gomobile_version() -> str:
    """The ``golang.org/x/mobile`` version ``transport/go.mod`` pins.

    Returns:
        The pseudo-version, as ``go install`` takes it.

    Raises:
        SystemExit: When the module file pins none.
    """
    text = (REPO_ROOT / "transport" / "go.mod").read_text(encoding="utf-8")
    match = re.search(rf"^\s*{re.escape(GO_MOBILE_MODULE)}\s+(\S+)", text, re.MULTILINE)
    if match is None:
        raise SystemExit("transport/go.mod pins no golang.org/x/mobile")
    return match.group(1)


def install_gomobile() -> Path:
    """Install ``gomobile`` and ``gobind`` at the pinned version, once.

    Returns:
        The directory holding both, for the path of a bind.

    Raises:
        SystemExit: When the install fails.
    """
    program = require_go()
    version = gomobile_version()
    directory = GO_TOOLS_DIR / f"mobile-{version}"
    if not (directory / "gomobile").exists() or not (directory / "gobind").exists():
        directory.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, GOBIN=str(directory), GOTOOLCHAIN="local")
        for tool in ("gomobile", "gobind"):
            command = [program, "install", f"{GO_MOBILE_MODULE}/cmd/{tool}@{version}"]
            print(" ".join(command))
            result = subprocess.run(command, env=environment, check=False)
            if result.returncode != 0:
                raise SystemExit(f"go install of {tool} exited {result.returncode}")
    return directory


def transport_source_digest() -> str:
    """A short digest of the transport module's sources, for a cache name.

    Returns:
        Eight hex digits of the SHA-256 over every Go file, ``go.mod`` and
        ``go.sum`` of ``transport/``, by path.
    """
    import hashlib

    digest = hashlib.sha256()
    root = REPO_ROOT / "transport"
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and (path.suffix == ".go" or path.name in ("go.mod", "go.sum"))
    )
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:8]
