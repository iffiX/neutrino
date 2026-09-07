"""Build the agent's Windows installer.

    python agent/packaging/build_msi.py --output-dir dist/ --architecture x64

An .msi rather than a wizard executable, because that is what the agent
installs when it updates itself: the self-update path hands ``msiexec`` a file
the hub served, and a package it cannot install unattended is not one.

The installer carries its own Python. Windows ships none, and the agent lands
on machines nobody has prepared, so the interpreter is python.org's embeddable
build, pinned by hash, with the window's whole Python side vendored beside it.

The agent runs as a real service: its entry answers the service control
manager over the ctypes handshake in ``platforms/windows_service.py``, so the
installer registers a service rather than a scheduled task.

WebView2 is the one thing the machine may still lack. Windows 11 and any
updated Windows 10 carry the Evergreen runtime; LTSC and Server editions do
not, so Microsoft's bootstrapper travels in the package and runs when the
runtime's registry key is absent.

Needs WiX: ``dotnet tool install --global wix``.

Not pure: downloads an interpreter and wheels, writes a package tree, runs wix.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import xml.sax.saxutils
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import icons  # noqa: E402
import payload  # noqa: E402

# The service the installer registers is the one the runtime reads and starts,
# named in the package so the two cannot drift.
from neutrino_agent.constants import (  # noqa: E402
    AGENT_SERVICE_DISPLAY_NAME_WINDOWS,
    AGENT_SERVICE_NAME_WINDOWS,
)

AGENT_ROOT = payload.AGENT_ROOT
REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the installer carries, one build per machine. Pinned by
# hash: a package that installs an unverified interpreter as SYSTEM is not one
# to ship.
WINDOWS_PYTHON_VERSION = "3.13.7"
WINDOWS_PYTHON_URL = (
    "https://www.python.org/ftp/python/{version}/python-{version}-embed-{machine}.zip"
)
WINDOWS_PYTHON_ABI = "cp313"
WINDOWS_PYTHON_SHA256 = {
    "amd64": "f6cca216a359be84797cabb54149ce5e062afb16cc7567eb7fc51cacb2d86b65",  # scan: allow
    "arm64": "2ddcf25e71f7205e652ebb57439f22fd2bab37d7f5c9152dbe32867bf2c77a50",  # scan: allow
}

# What each name for the machine maps to: the interpreter download's own, and
# the platform an msi declares.
WINDOWS_MACHINES = {"x86_64": "amd64", "aarch64": "arm64"}
MSI_PLATFORMS = {"amd64": "x64", "arm64": "arm64"}

# The window's Python side, pinned to the file. pywebview drives the WebView2
# control through pythonnet, which reaches .NET through clr-loader and cffi;
# the rest is what pywebview itself imports.
WINDOWS_WHEELS = (
    (
        "pywebview",
        "6.2.1",
        "https://files.pythonhosted.org/packages/3d/25/"
        "9491695c22c4842c5b3903b4dc172e0eecf67a27c0af34a71512c9b76a0a/"
        "pywebview-6.2.1-py3-none-any.whl",
        "9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46",  # scan: allow
    ),
    (
        "pythonnet",
        "3.1.0",
        "https://files.pythonhosted.org/packages/ac/4b/"
        "52414f442624d2589f5374a48c08d5ae94f24bea67fc13a20a752884e5b7/"
        "pythonnet-3.1.0-cp310.cp311.cp312.cp313.cp314-none-any.whl",
        "698dd88edc198819ad63b624a6ebe76208c7b46e4fe13626f65e484f0358d6ba",  # scan: allow
    ),
    (
        "clr-loader",
        "0.3.1",
        "https://files.pythonhosted.org/packages/5e/da/"
        "ec1a6e36624000b6df0dd61183c42342ee5814c073315e802cadaad04d2f/"
        "clr_loader-0.3.1-py3-none-any.whl",
        "cbad189de20d202a7d621956b0fc38049e13c9bf7ca2923441eff725cd121aa1",  # scan: allow
    ),
    (
        "pycparser",
        "2.22",
        "https://files.pythonhosted.org/packages/13/a3/"
        "a812df4e2dd5696d1f351d58b8fe16a405b234ad2886a0dab9183fb78109/"
        "pycparser-2.22-py3-none-any.whl",
        "c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",  # scan: allow
    ),
    (
        "bottle",
        "0.13.4",
        "https://files.pythonhosted.org/packages/83/f6/"
        "b55ec74cfe68c6584163faa311503c20b0da4c09883a41e8e00d6726c954/"
        "bottle-0.13.4-py2.py3-none-any.whl",
        "045684fbd2764eac9cdeb824861d1551d113e8b683d8d26e296898d3dd99a12e",  # scan: allow
    ),
    (
        "typing_extensions",
        "4.16.0",
        "https://files.pythonhosted.org/packages/49/d3/"
        "b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/"
        "typing_extensions-4.16.0-py3-none-any.whl",
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",  # scan: allow
    ),
    (
        "proxy_tools",
        "0.1.0",
        "https://files.pythonhosted.org/packages/f2/cf/"
        "77d3e19b7fabd03895caca7857ef51e4c409e0ca6b37ee6e9f7daa50b642/"
        "proxy_tools-0.1.0.tar.gz",
        "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010",  # scan: allow
    ),
)

# The one wheel that is compiled, so one file per machine.
WINDOWS_CFFI = {
    "amd64": (
        "cffi",
        "2.1.1",
        "https://files.pythonhosted.org/packages/60/a6/"
        "8b149b2c3f2e11aaa1618ef64500b45f50f22c57a977a4dff1aff1f91042/"
        "cffi-2.1.1-cp313-cp313-win_amd64.whl",
        "1aa5645c30469b09530c4ebca77ebf8f17618293c58f8549cb1a543a50236e7d",  # scan: allow
    ),
    "arm64": (
        "cffi",
        "2.1.1",
        "https://files.pythonhosted.org/packages/01/9a/"
        "11f687cb39d6a3504060d5242f04f48c735afb4d3d533958a20594890cb2/"
        "cffi-2.1.1-cp313-cp313-win_arm64.whl",
        "63bbfd5ded17c4840ac07cd8f1c21ba9d9708141f840b324f422f41b207e3973",  # scan: allow
    ),
}

# Microsoft's Evergreen bootstrapper. The only carried file with no hash of
# its own: the link serves whatever the current runtime installer is, and
# Microsoft publishes no digest for it. What can be checked is checked — that
# it is a Windows executable of a plausible size.
WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_BOOTSTRAPPER_NAME = "MicrosoftEdgeWebview2Setup.exe"
WEBVIEW2_BOOTSTRAPPER_MIN_BYTES = 500 * 1024
WEBVIEW2_BOOTSTRAPPER_MAX_BYTES = 20 * 1024 * 1024

# Where the Evergreen runtime records itself, per machine. Absent means the
# bootstrapper has something to do. The identifier is Microsoft's published
# one for the runtime, the same on every Windows machine.
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"  # scan: allow
WEBVIEW2_REGISTRY_KEY = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}"

# The identity of the product across every version it ever ships as. Fixed:
# changing it makes an upgrade install beside the old one instead of over it.
UPGRADE_CODE = "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"

CONSOLE_WRAPPER = """@echo off
rem Run the agent in a terminal, for `nagent status` and for reading errors.
"%~dp0python\\python.exe" -m neutrino_agent.cli.entry %*
"""

# @NAME@ rather than str.format: the source is XML with braces of its own in
# the property expressions.
WIX_SOURCE = r"""<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">
  <Package Name="Neutrino Agent"
           Manufacturer="@PUBLISHER@"
           Version="@VERSION@"
           UpgradeCode="@UPGRADE_CODE@"
           Scope="perMachine"
           Compressed="yes">
    <MajorUpgrade AllowSameVersionUpgrades="yes"
                  DowngradeErrorMessage="A newer Neutrino Agent is already installed." />
    <MediaTemplate EmbedCab="yes" />
    <Icon Id="AgentIcon" SourceFile="@ICON@" />
    <Property Id="ARPPRODUCTICON" Value="AgentIcon" />

    <!-- The runtime records itself here; absent, the bootstrapper runs. -->
    <Property Id="WEBVIEW2INSTALLED" Secure="yes">
      <RegistrySearch Id="WebView2Client"
                      Root="HKLM"
                      Key="@WEBVIEW2_KEY@"
                      Name="pv"
                      Type="raw"
                      Bitness="always32" />
    </Property>

    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="INSTALLFOLDER" Name="Neutrino Agent" />
    </StandardDirectory>
    <StandardDirectory Id="ProgramMenuFolder" />

    <ComponentGroup Id="Payload" Directory="INSTALLFOLDER">
      <Files Include="@PAYLOAD@\**" />
      <!-- The interpreter itself is the service host, under its own name
           and beside its DLL and ._pth. Not a renamed copy: an interpreter
           under another name is what a Python trojan looks like, and the
           antivirus engines say so. -->
      <Component Id="ServiceHost" Guid="*" Subdirectory="python">
        <File Id="ServiceHostExe"
              Source="@SERVICE_HOST@"
              Name="pythonw.exe"
              KeyPath="yes" />
        <ServiceInstall Id="AgentService"
                        Name="@SERVICE_NAME@"
                        DisplayName="@SERVICE_DISPLAY_NAME@"
                        Description="Keeps this machine's modules in the state its Neutrino Hub asks for."
                        Type="ownProcess"
                        Start="auto"
                        ErrorControl="normal"
                        Arguments="-m neutrino_agent.cli.entry run --windows-service"
                        Vital="yes" />
        <ServiceControl Id="AgentServiceControl"
                        Name="@SERVICE_NAME@"
                        Start="install"
                        Stop="both"
                        Remove="uninstall"
                        Wait="yes" />
      </Component>
      <Component Id="WebView2Bootstrapper" Guid="*">
        <File Id="WebView2BootstrapperExe"
              Source="@BOOTSTRAPPER@"
              Name="@BOOTSTRAPPER_NAME@"
              KeyPath="yes" />
      </Component>
      <Component Id="StartMenuShortcut" Guid="*">
        <Shortcut Id="AgentWindowShortcut"
                  Directory="ProgramMenuFolder"
                  Name="Neutrino Agent"
                  Description="Join a Neutrino Hub and choose what this machine runs"
                  Target="[INSTALLFOLDER]python\pythonw.exe"
                  Arguments="-m neutrino_agent.cli.entry gui"
                  WorkingDirectory="INSTALLFOLDER"
                  Icon="AgentIcon" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Agent"
                       Name="Shortcut"
                       Type="integer"
                       Value="1"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    <CustomAction Id="InstallWebView2"
                  FileRef="WebView2BootstrapperExe"
                  ExeCommand="/silent /install"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore" />
    <InstallExecuteSequence>
      <Custom Action="InstallWebView2"
              After="InstallFiles"
              Condition="NOT WEBVIEW2INSTALLED AND NOT REMOVE" />
    </InstallExecuteSequence>

    <Feature Id="Main" Title="Neutrino Agent" Level="1">
      <ComponentGroupRef Id="Payload" />
    </Feature>
  </Package>
</Wix>
"""


def main() -> int:
    """Build the installer.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .msi")
    parser.add_argument(
        "--architecture", default="x64", help="the architecture to build for"
    )
    parser.add_argument(
        "--publisher",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Manufacturer field",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="write and check the payload, then stop before wix",
    )
    arguments = parser.parse_args()

    version = payload.version()
    machine = WINDOWS_MACHINES[payload.machine_name(arguments.architecture)]
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{PACKAGE_NAME}-{version}-{machine}.msi"

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(root, version, machine)
        source = root / "neutrino_agent.wxs"
        source.write_text(
            WIX_SOURCE.replace("@VERSION@", version)
            # Every value lands inside an XML attribute; a publisher with
            # an address in angle brackets is an ordinary name and must not
            # become markup.
            .replace("@PUBLISHER@", xml.sax.saxutils.escape(arguments.publisher))
            .replace("@UPGRADE_CODE@", UPGRADE_CODE)
            .replace("@PAYLOAD@", str(staged["payload"]))
            .replace("@SERVICE_HOST@", str(staged["service_host"]))
            .replace("@BOOTSTRAPPER@", str(staged["bootstrapper"]))
            .replace("@BOOTSTRAPPER_NAME@", WEBVIEW2_BOOTSTRAPPER_NAME)
            .replace("@ICON@", str(staged["icon"]))
            .replace("@SERVICE_NAME@", AGENT_SERVICE_NAME_WINDOWS)
            .replace("@SERVICE_DISPLAY_NAME@", AGENT_SERVICE_DISPLAY_NAME_WINDOWS)
            .replace("@WEBVIEW2_KEY@", WEBVIEW2_REGISTRY_KEY),
            encoding="utf-8",
        )
        if arguments.stage_only:
            print(f"staged {staged['payload']} and {source}")
            return 0
        _build(source, target, machine)

    if not target.is_file():
        raise SystemExit(f"wix wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(root: Path, version: str, machine: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``amd64`` or ``arm64``.

    Returns:
        The paths the installer's source names: the payload directory, the
        service host, the bootstrapper and the icon.
    """
    installed = root / "payload"
    python_dir = installed / "python"
    python_dir.mkdir(parents=True)

    archive = root / "python-embed.zip"
    archive.write_bytes(
        payload.fetch(
            WINDOWS_PYTHON_URL.format(version=WINDOWS_PYTHON_VERSION, machine=machine),
            WINDOWS_PYTHON_SHA256[machine],
            "the interpreter",
        )
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(python_dir)
    _open_import_path(python_dir)

    payload.stage_agent_tree(installed, version)
    payload.stage_wheels(
        Path(sys.executable),
        installed / "lib",
        WINDOWS_WHEELS + (WINDOWS_CFFI[machine],),
        platform_tag=f"win_{machine}",
        abi_tag=WINDOWS_PYTHON_ABI,
    )
    (installed / "nagent.cmd").write_text(CONSOLE_WRAPPER, encoding="utf-8")

    # Named files the installer's source points at directly, kept out of the
    # payload directory so the file glob does not claim them twice.
    # pythonw.exe leaves the payload tree to be placed by the service's own
    # component, back where it came from; the glob must not claim it too.
    service_host = root / "pythonw.exe"
    shutil.move(str(python_dir / "pythonw.exe"), str(service_host))
    bootstrapper = root / WEBVIEW2_BOOTSTRAPPER_NAME
    bootstrapper.write_bytes(_fetch_bootstrapper())
    icon = icons.write_ico(root / "neutrino_agent.ico")
    return {
        "payload": installed,
        "service_host": service_host,
        "bootstrapper": bootstrapper,
        "icon": icon,
    }


def _fetch_bootstrapper() -> bytes:
    """Download Microsoft's WebView2 bootstrapper.

    Returns:
        The installer's bytes.

    Raises:
        SystemExit: When what arrives is not a Windows executable, or is not
            the size one is.
    """
    import urllib.request

    print(f"  fetching {WEBVIEW2_BOOTSTRAPPER_NAME}")
    with urllib.request.urlopen(WEBVIEW2_BOOTSTRAPPER_URL, timeout=600) as response:
        content = response.read()
    if not content.startswith(b"MZ"):
        raise SystemExit(
            f"{WEBVIEW2_BOOTSTRAPPER_URL} did not serve a Windows executable"
        )
    if not (
        WEBVIEW2_BOOTSTRAPPER_MIN_BYTES
        <= len(content)
        <= WEBVIEW2_BOOTSTRAPPER_MAX_BYTES
    ):
        raise SystemExit(
            f"the WebView2 bootstrapper is {len(content)} bytes, outside the "
            f"{WEBVIEW2_BOOTSTRAPPER_MIN_BYTES}-{WEBVIEW2_BOOTSTRAPPER_MAX_BYTES} "
            "a bootstrapper is"
        )
    return content


def _open_import_path(python_dir: Path) -> None:
    """Let the bundled interpreter see the agent and the vendored packages.

    The embeddable package resolves imports from its ``._pth`` file alone and
    ignores PYTHONPATH, so everything beside it is invisible until the file
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
        raise SystemExit(f"no '.' entry in {path_file.name} to add the rest beside")
    at = lines.index(".") + 1
    lines[at:at] = ["..", "..\\lib"]
    path_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build(source: Path, target: Path, machine: str) -> None:
    """Run wix over the generated source.

    Args:
        source: The .wxs to compile.
        target: Where the .msi should land.
        machine: ``amd64`` or ``arm64``, which the msi declares as its
            platform.

    Raises:
        SystemExit: If WiX is not installed, or refuses the source.
    """
    wix = shutil.which("wix")
    if wix is None:
        raise SystemExit(
            "WiX is needed to build the Windows installer: "
            "dotnet tool install --global wix"
        )
    result = subprocess.run(
        [
            wix,
            "build",
            "-arch",
            MSI_PLATFORMS[machine],
            "-out",
            str(target),
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit((result.stdout or result.stderr).strip())


if __name__ == "__main__":
    raise SystemExit(main())
