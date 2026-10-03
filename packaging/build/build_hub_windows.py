"""Build the hub's Windows installer.

    python packaging/build/build_hub_windows.py --output-dir dist/ --architecture x64 \
        --agent-packages dist/ --packet-dll build/packet_stub/packet.dll

Runs on: Windows on x86-64, with Python 3.13 and WiX 6, after ``npm run
build`` in ``hub/frontend``. ``--agent-packages`` names a directory holding
the agent's ``.msi``, built before, and ``--packet-dll`` the stand-in
``packet.dll`` built from ``client/desktop/packaging/packet_stub.c``.

The installer carries the hub compiled: Nuitka turns the package and the
interpreter it runs on into ``nhub.exe``, a console program, with the
libraries and ``neutrino_hub/data`` beside it, under
``C:\\Program Files\\Neutrino\\hub``, which goes on PATH. Under its ``bin``
are xray, cli-proxy-api, netbird, easytier-core, easytier-cli and
tun2socks, with EasyTier's ``wintun.dll`` and the stand-in ``packet.dll``
beside them. The
geodata and the agent's ``.msi`` land under the state directory in
``C:\\ProgramData\\Neutrino\\hub``, which the installer creates open to SYSTEM
and the administrators alone, every agent package in the directory named
in the manifest.

The installer registers the ``neutrino_hub`` service, run as LocalSystem at
boot with ``service run`` and recovered when it ends, and starts it, on a
fresh install and on an upgrade; until the box is set up it serves the
setup wizard. The Start menu shortcut ``Neutrino Hub`` runs ``nhub.exe
open``.

Needs WiX 6 and its Util extension: ``dotnet tool install --global wix
--version 6.0.2`` and ``wix extension add -g WixToolset.Util.wixext/6.0.2``.

Not pure: makes a virtual environment, downloads a compiler and the
programs the hub drives, compiles, writes a package tree, runs wix.
"""

import argparse
import platform
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hub" / "packaging"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import compiled_tree  # noqa: E402
from shared import hub_assets  # noqa: E402
from shared import wix_build  # noqa: E402
from shared.constants import PACKAGING_ASSET_PATTERNS  # noqa: E402
import venv_tree  # noqa: E402

sys.path.append(
    str(Path(__file__).resolve().parents[2] / "client" / "desktop" / "packaging")
)
import icons  # noqa: E402

PACKAGE_NAME = compiled_tree.PACKAGE_NAME

# The compiled hub, a console program: the service control manager starts
# it with no console, and an administrator's terminal gets its output.
HUB_BINARY_NAME = "nhub.exe"
HUB_SERVICE_NAME = "neutrino_hub"
HUB_SERVICE_ARGUMENTS = "service run"
# Where the programs the hub drives sit, under the program folder.
PROGRAMS_DIR_NAME = "bin"
# The stand-in for Npcap's Packet.dll, as it lands beside easytier-core.exe.
PACKET_DLL_NAME = "packet.dll"

# x64 only: the agent the hub carries is published for no Windows arm64.
# Every name a command line or Windows itself gives the machine.
WINDOWS_MACHINES = {"x64": "amd64", "amd64": "amd64", "x86_64": "amd64"}
# The agent package family a Windows hub seeds.
AGENT_FAMILY = "msi"

# The identity of the product across every version it ever ships as. Fixed:
# changing it makes an upgrade install beside the old one instead of over it.
UPGRADE_CODE = "5B0C1E7A-3D2F-4E8B-9A61-2C7D4F0E8B53"

# The data folder's whole security descriptor: SYSTEM and the administrators,
# inherited by everything under it, and nothing inherited from ProgramData,
# whose own grants let every account read. The agent's data folder has the
# same.
DATA_FOLDER_SDDL = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

# What the service control manager does when the hub ends without being
# stopped: start it again.
SERVICE_RECOVERY = (
    '<util:ServiceConfig FirstFailureActionType="restart" '
    'SecondFailureActionType="restart" ThirdFailureActionType="restart" '
    'RestartServiceDelayInSeconds="10" ResetPeriodInDays="1" />'
)

# The application entry in the Start menu.
ENTRY_NAME = "Neutrino Hub"
ENTRY_ARGUMENTS = "open"

# The package's body, inside the Package element wix_build writes around it.
WIX_BODY = r"""
    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="NeutrinoProgramFolder" Name="Neutrino">
        <Directory Id="INSTALLFOLDER" Name="hub" />
      </Directory>
    </StandardDirectory>
    <StandardDirectory Id="ProgramMenuFolder" />
    <Icon Id="HubIcon" SourceFile="@ICON@" />
    <Property Id="ARPPRODUCTICON" Value="HubIcon" />

    <StandardDirectory Id="CommonAppDataFolder">
      <Directory Id="NeutrinoDataFolder" Name="Neutrino">
        <Directory Id="HUBDATAFOLDER" Name="hub">
          <Directory Id="HUBSTATEFOLDER" Name="state" />
        </Directory>
      </Directory>
    </StandardDirectory>

    <ComponentGroup Id="Payload" Directory="INSTALLFOLDER">
      <Files Include="@PAYLOAD@\**" />
      @SERVICE_COMPONENT@
      <Component Id="PathEntry" Guid="*">
        <Environment Id="HubPath"
                     Name="PATH"
                     Value="[INSTALLFOLDER]"
                     Part="last"
                     Action="set"
                     System="yes" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Hub"
                       Name="Path"
                       Type="integer"
                       Value="1"
                       KeyPath="yes" />
      </Component>
      <Component Id="StartMenuShortcut" Guid="*">
        <Shortcut Id="HubEntryShortcut"
                  Directory="ProgramMenuFolder"
                  Name="@ENTRY_NAME@"
                  Description="Open the hub's panel"
                  Target="[INSTALLFOLDER]@BINARY@"
                  Arguments="@ENTRY_ARGUMENTS@"
                  WorkingDirectory="INSTALLFOLDER"
                  Show="minimized"
                  Icon="HubIcon" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Hub"
                       Name="Shortcut"
                       Type="integer"
                       Value="1"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    <!-- The vault key, the TLS private keys and the session secret live
         here, so the folder admits SYSTEM and the administrators and
         nobody else. -->
    <ComponentGroup Id="Data" Directory="HUBDATAFOLDER">
      <Component Id="HubDataFolder" Guid="*">
        <CreateFolder>
          <PermissionEx Sddl="@DATA_SDDL@" />
        </CreateFolder>
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Hub"
                       Name="DataFolder"
                       Type="string"
                       Value="[HUBDATAFOLDER]"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    <!-- The geodata and the agent's own installer, seeded into the state
         directory the hub reads them from. -->
    <ComponentGroup Id="State" Directory="HUBSTATEFOLDER">
      <Files Include="@STATE@\**" />
    </ComponentGroup>

    <Feature Id="Main" Title="Neutrino Hub" Level="1" AllowAbsent="no">
      <ComponentGroupRef Id="Payload" />
      <ComponentGroupRef Id="Data" />
      <ComponentGroupRef Id="State" />
    </Feature>
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
        "--agent-packages",
        required=True,
        help="a directory of agent packages already built, the agent's .msi "
        "among them",
    )
    parser.add_argument(
        "--agent-package-url-base",
        default="",
        help="where a release publishes the agent packages the manifest names",
    )
    parser.add_argument(
        "--packet-dll",
        default="",
        help="the stand-in packet.dll built from packet_stub.c",
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
    _check_tools(arguments.stage_only)

    version = venv_tree.version()
    machine = windows_machine(arguments.architecture)
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / msi_name(version, machine)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(
            root,
            version,
            machine,
            agent_packages=Path(arguments.agent_packages).resolve(),
            url_base=arguments.agent_package_url_base,
            packet_dll=Path(arguments.packet_dll) if arguments.packet_dll else None,
        )
        source = root / "neutrino_hub.wxs"
        source.write_text(wix_source(staged, version, arguments.publisher), "utf-8")
        if arguments.stage_only:
            print(f"staged {staged['payload']} and {source}")
            return 0
        wix_build.build(
            source, target, machine, extensions=(wix_build.WIX_UTIL_EXTENSION,)
        )

    if not target.is_file():
        raise SystemExit(f"wix wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def windows_machine(architecture: str) -> str:
    """The platform name the installer carries for a machine.

    Args:
        architecture: The architecture, named however the command line
            names it.

    Returns:
        ``amd64``.

    Raises:
        SystemExit: When it is not a machine the hub is published for on
            Windows.
    """
    machine = WINDOWS_MACHINES.get(architecture.lower())
    if machine is None:
        raise SystemExit(f"the Windows hub is published for x64, not {architecture}")
    return machine


def msi_name(version: str, machine: str) -> str:
    """What the installer is called, the way the release publishes it.

    Args:
        version: The version being packaged, or ``{version}`` to leave it
            open for the stamp.
        machine: ``amd64``.

    Returns:
        The file name.
    """
    return PACKAGING_ASSET_PATTERNS["msi"].format(
        name=PACKAGE_NAME, version=version, architecture=machine
    )


def wix_source(staged: dict, version: str, publisher: str) -> str:
    """The installer's source with every value filled in.

    Args:
        staged: What :func:`_lay_out` wrote: ``payload``, ``binary``,
            ``state`` and ``icon``.
        version: The version being packaged.
        publisher: The Manufacturer field's value.

    Returns:
        The .wxs document.
    """
    service = wix_build.service_component(
        component_id="HubService",
        source=staged["binary"],
        service_name=HUB_SERVICE_NAME,
        display_name="Neutrino Hub",
        description="Serves the Neutrino panel and runs the daemons it drives.",
        arguments=HUB_SERVICE_ARGUMENTS,
        account="LocalSystem",
        start="auto",
        permissions=(SERVICE_RECOVERY,),
    )
    body = wix_build.fill(
        WIX_BODY,
        {
            "PAYLOAD": staged["payload"],
            "STATE": staged["state"],
            "DATA_SDDL": DATA_FOLDER_SDDL,
            "ICON": staged["icon"],
            "ENTRY_NAME": ENTRY_NAME,
            "ENTRY_ARGUMENTS": ENTRY_ARGUMENTS,
            "BINARY": HUB_BINARY_NAME,
        },
    )
    body = body.replace("@SERVICE_COMPONENT@", service)
    return wix_build.package_source(
        name="Neutrino Hub",
        manufacturer=publisher,
        version=version,
        upgrade_code=UPGRADE_CODE,
        body=body,
    )


def _lay_out(
    root: Path,
    version: str,
    machine: str,
    *,
    agent_packages: Path,
    url_base: str,
    packet_dll: "Path | None",
) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``amd64``.
        agent_packages: The directory the agent's packages are in.
        url_base: Where a release publishes them, empty for none.
        packet_dll: The stand-in packet.dll; None refuses the build.

    Returns:
        The paths the installer's source names: the payload directory, the
        hub's own binary, kept out of the payload so the service component
        can claim it, the state directory's seed, and the entry's icon.

    Raises:
        SystemExit: When there is no stand-in packet.dll, this Python is
            not the pinned minor, the machine asked for is not this one, the
            compile writes no binary, a carried file is not what was pinned,
            or no agent package is there for the machine.
    """
    _check_packet_dll(packet_dll)
    _check_build_machine(machine)
    tree = root / "tree"
    compiled_tree.stage_hub_tree(tree, version, msi_name("{version}", machine))

    python = compiled_tree.make_build_environment(root / "venv")
    dist = compiled_tree.compile_hub(
        python,
        tree,
        root / "build",
        HUB_BINARY_NAME,
        options=(
            "--windows-console-mode=force",
            "--product-name=Neutrino Hub",
            f"--product-version={version}",
            f"--file-version={version}",
        ),
    )

    installed = root / "payload"
    installed.mkdir(parents=True)
    for item in dist.iterdir():
        if item.name == HUB_BINARY_NAME:
            continue
        if item.is_dir():
            shutil.copytree(item, installed / item.name)
        else:
            shutil.copyfile(item, installed / item.name)
    binary = root / HUB_BINARY_NAME
    shutil.copyfile(dist / HUB_BINARY_NAME, binary)
    programs = installed / PROGRAMS_DIR_NAME
    hub_assets.stage_programs(programs, "windows", machine)
    shutil.copyfile(packet_dll, programs / PACKET_DLL_NAME)
    compiled_tree.stage_licenses(installed / "licenses")

    state = root / "state"
    hub_assets.stage_geodata(state / compiled_tree.GEODATA_DIR_NAME)
    compiled_tree.seed_agent_cache(
        agent_packages,
        state / compiled_tree.AGENT_CACHE_DIR_NAME,
        installed / "neutrino_hub" / compiled_tree.DATA_DIR_NAME,
        family=AGENT_FAMILY,
        machine=machine,
        url_base=url_base,
    )
    icon = icons.write_ico(root / "neutrino_hub.ico")
    return {"payload": installed, "binary": binary, "state": state, "icon": icon}


def _check_packet_dll(packet_dll: "Path | None") -> None:
    """Refuse a build without the stand-in packet.dll.

    Args:
        packet_dll: Its path, None when the command line named none.

    Raises:
        SystemExit: When it was not named, is not there, or is not a
            Windows library.
    """
    if packet_dll is None:
        raise SystemExit(
            "easytier-core does not start without a packet.dll beside it; "
            "build one from client/desktop/packaging/packet_stub.c and pass "
            "--packet-dll"
        )
    if not packet_dll.is_file():
        raise SystemExit(f"there is no packet.dll at {packet_dll}")
    if not packet_dll.read_bytes().startswith(b"MZ"):
        raise SystemExit(f"{packet_dll} is not a Windows library")


def _check_build_machine(machine: str) -> None:
    """Refuse a build that would carry another interpreter than the pinned
    one, or one for a machine this is not.

    Args:
        machine: ``amd64``, as asked for.

    Raises:
        SystemExit: On either mismatch.
    """
    compiled_tree.check_build_python()
    if WINDOWS_MACHINES.get(platform.machine().lower()) != machine:
        raise SystemExit(
            f"an installer for {machine} is compiled on a {machine} machine; "
            f"this one is {platform.machine()}"
        )


def _check_tools(is_stage_only: bool) -> None:
    """Refuse to start on a machine that cannot finish the build.

    Args:
        is_stage_only: Whether the build stops before wix.

    Raises:
        SystemExit: When this is not Windows, or WiX is missing.
    """
    if sys.platform != "win32":
        raise SystemExit(f"{Path(__file__).name} runs on Windows; this is {sys.platform}")
    if not is_stage_only and shutil.which("wix") is None:
        raise SystemExit(
            "WiX 6 is needed and wix is not on the path: "
            "dotnet tool install --global wix --version 6.0.2"
        )


if __name__ == "__main__":
    raise SystemExit(main())
