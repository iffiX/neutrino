"""Build the agent's Windows installer.

    python packaging/build/build_agent_windows.py --output-dir dist/ --architecture x64

Runs on: Windows on x86-64, with Python 3.13 and WiX 6.

The installer carries the agent compiled: Nuitka turns the package and the
interpreter it runs on into ``nagent.exe``, a console program, with the
libraries beside it. The installer registers it as the ``neutrino_agent``
service, run as LocalSystem at boot with ``service run``, puts its folder on
PATH so an administrator's terminal answers ``nagent``, and creates the data
folder under ``%ProgramData%`` open to SYSTEM and the administrators alone.

RustDesk comes as the files upstream's pinned executable packs, unpacked at
build time and checked file by file, laid down in the agent's own folder
under ``rustdesk``: the same files upstream's own install copies into
``%ProgramFiles%\\RustDesk``. The installer runs nothing of RustDesk's and
registers nothing of it, no service, no uninstall entry, no driver and no
firewall rule: the agent registers its copy when the hub's Remote desktop
switch is on. An earlier package that ran upstream's installer is known by
the copy of it that package left in its folder, found before the earlier
version is removed; the upgrade then runs upstream's install with
``--uninstall``, as its own uninstall entry does. A RustDesk no package of
the agent installed stays.

Removing the agent also runs ``nagent service uninstall --yes`` before its
files go, which unregisters the scheduled tasks and removes the firewall
rules its modules added, the file share's fence among them. Shares and
accounts stay, and an upgrade runs neither action.

Needs WiX 6 and its Util extension: ``dotnet tool install --global wix
--version 6.0.2`` and ``wix extension add -g WixToolset.Util.wixext/6.0.2``,
and the Python package ``brotli`` to unpack RustDesk's files.

Not pure: makes a virtual environment, downloads a compiler and RustDesk,
compiles, writes a package tree, runs wix.
"""

import argparse
import importlib.util
import platform
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "packaging"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
from shared import edition_build  # noqa: E402
from shared import nuitka_build  # noqa: E402
import payload  # noqa: E402
from shared import rustdesk_assets  # noqa: E402
from shared import wix_build  # noqa: E402
from shared.constants import PACKAGING_ASSET_PATTERNS  # noqa: E402

REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the agent is compiled against is the one running this
# script. One minor, checked, the same as the client's.
BUILD_PYTHON_VERSION = (3, 13)

# The compiled agent, a console program: the service control manager starts
# it with no console, and an administrator's terminal gets its output.
AGENT_BINARY_NAME = "nagent.exe"
AGENT_SERVICE_NAME = "neutrino_agent"
AGENT_SERVICE_ARGUMENTS = "service run"

# x64 only: RustDesk publishes no Windows arm64 build to carry.
WINDOWS_MACHINES = {"x86_64": "amd64"}

# Where the agent's copy of RustDesk lies under its folder.
RUSTDESK_DIR_NAME = "rustdesk"
# What every earlier package that ran upstream's installer left in its
# folder: upstream's executable under the name upstream publishes it as,
# 1.4.9 the only version any package carried, in each folder under
# Program Files an earlier package installed into. Its being there is what
# says the RustDesk under Program Files is that package's.
OLD_RUSTDESK_INSTALLER_NAME = "rustdesk-1.4.9-x86_64.exe"
OLD_AGENT_FOLDERS = ("Neutrino Agent", "Neutrino\\agent")
# The property the search sets to the copy's path when it finds one.
OLD_RUSTDESK_PROPERTY = "OLDRUSTDESKINSTALLER"

# The identity of the product across every version it ever ships as. Fixed:
# changing it makes an upgrade install beside the old one instead of over it.
UPGRADE_CODE = "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"

# The data folder's whole security descriptor: SYSTEM and the administrators,
# inherited by everything under it, and nothing inherited from ProgramData,
# whose own grants let every account read.
DATA_FOLDER_SDDL = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

# What the modules added is taken away when the agent is removed, and kept
# through an upgrade, whose removal of the old version carries the upgrading
# code.
AGENT_REMOVED_CONDITION = 'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'
# An install over an earlier package that ran upstream's installer.
OLD_RUSTDESK_CONDITION = f"{OLD_RUSTDESK_PROPERTY} AND NOT REMOVE"
# What upstream's uninstall entry runs: its install, with --uninstall. Runs
# as the system once the earlier version is gone, which leaves upstream's
# install where it was, from Program Files, since the agent's folder may
# have gone with it.
OLD_RUSTDESK_UNINSTALL = '"[ProgramFiles64Folder]RustDesk\\rustdesk.exe" --uninstall'
# What the removal runs the agent with to take away what its modules added.
AGENT_UNINSTALL_ARGUMENTS = "service uninstall --yes"

# What the service control manager does when the agent ends without being
# stopped: start it again.
SERVICE_RECOVERY = (
    '<util:ServiceConfig FirstFailureActionType="restart" '
    'SecondFailureActionType="restart" ThirdFailureActionType="restart" '
    'RestartServiceDelayInSeconds="10" ResetPeriodInDays="1" />'
)

# The package's body, inside the Package element wix_build writes around it.
WIX_BODY = r"""
    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="NeutrinoProgramFolder" Name="Neutrino">
        <Directory Id="INSTALLFOLDER" Name="agent" />
      </Directory>
    </StandardDirectory>
    <StandardDirectory Id="CommonAppDataFolder">
      <Directory Id="NeutrinoDataFolder" Name="Neutrino">
        <Directory Id="AGENTDATAFOLDER" Name="agent" />
      </Directory>
    </StandardDirectory>

    <ComponentGroup Id="Payload" Directory="INSTALLFOLDER">
      <Files Include="@PAYLOAD@\**" />
      @SERVICE_COMPONENT@
      <Component Id="PathEntry" Guid="*">
        <Environment Id="AgentPath"
                     Name="PATH"
                     Value="[INSTALLFOLDER]"
                     Part="last"
                     Action="set"
                     System="yes" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Agent"
                       Name="Path"
                       Type="integer"
                       Value="1"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    <!-- The binding, the state and the seat password live here, so the
         folder admits SYSTEM and the administrators and nobody else. -->
    <ComponentGroup Id="Data" Directory="AGENTDATAFOLDER">
      <Component Id="AgentDataFolder" Guid="*">
        <CreateFolder>
          <PermissionEx Sddl="@DATA_SDDL@" />
        </CreateFolder>
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Agent"
                       Name="DataFolder"
                       Type="string"
                       Value="[AGENTDATAFOLDER]"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    @OLD_RUSTDESK_SEARCH@
    @REMOVE_OLD_RUSTDESK@
    @UNINSTALL_ADDED@

    <InstallExecuteSequence>
      <Custom Action="RemoveOldRustDesk"
              After="InstallInitialize"
              Condition="@OLD_RUSTDESK@" />
      <Custom Action="UninstallAdded"
              Before="RemoveFiles"
              Condition="@AGENT_REMOVED@" />
    </InstallExecuteSequence>

    <Feature Id="Main" Title="Neutrino Agent" Level="1" AllowAbsent="no">
      <ComponentGroupRef Id="Payload" />
      <ComponentGroupRef Id="Data" />
    </Feature>
"""


def main() -> int:
    """Build the installer.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
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
    edition_build.require_edition_tree(arguments.edition)
    _check_tools(arguments.stage_only)

    version = payload.version()
    machine = windows_machine(arguments.architecture)
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / msi_name(version, machine)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(root, version, machine)
        source = root / "neutrino_agent.wxs"
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
        SystemExit: When it is not a machine the agent is published for on
            Windows.
    """
    name = payload.machine_name(architecture)
    if name not in WINDOWS_MACHINES:
        raise SystemExit(f"the Windows agent is published for x64, not {architecture}")
    return WINDOWS_MACHINES[name]


def msi_name(version: str, machine: str) -> str:
    """What the installer is called, the way the release publishes it.

    Args:
        version: The version being packaged.
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
        staged: What :func:`_lay_out` wrote: ``payload`` and ``binary``.
        version: The version being packaged.
        publisher: The Manufacturer field's value.

    Returns:
        The .wxs document.
    """
    service = wix_build.service_component(
        component_id="AgentService",
        source=staged["binary"],
        service_name=AGENT_SERVICE_NAME,
        display_name="Neutrino Agent",
        description="Keeps this machine in the state its Neutrino Hub asks for.",
        arguments=AGENT_SERVICE_ARGUMENTS,
        account="LocalSystem",
        start="auto",
        permissions=(SERVICE_RECOVERY,),
    )
    old_rustdesk_search = wix_build.element(
        "Property",
        {"Id": OLD_RUSTDESK_PROPERTY, "Secure": "yes"},
        tuple(
            wix_build.element(
                "DirectorySearch",
                {
                    "Id": f"OldAgentFolder{index}",
                    "Path": f"[ProgramFiles64Folder]{folder}",
                    "Depth": "0",
                },
                (
                    wix_build.element(
                        "FileSearch",
                        {
                            "Id": f"OldRustDeskCopy{index}",
                            "Name": OLD_RUSTDESK_INSTALLER_NAME,
                        },
                    ),
                ),
            )
            for index, folder in enumerate(OLD_AGENT_FOLDERS)
        ),
    )
    remove_old_rustdesk = wix_build.custom_action(
        "RemoveOldRustDesk",
        is_failure_ignored=True,
        Directory="ProgramFiles64Folder",
        ExeCommand=OLD_RUSTDESK_UNINSTALL,
    )
    uninstall_added = wix_build.custom_action(
        "UninstallAdded",
        is_failure_ignored=True,
        FileRef="AgentServiceFile",
        ExeCommand=AGENT_UNINSTALL_ARGUMENTS,
    )
    body = wix_build.fill(
        WIX_BODY,
        {
            "PAYLOAD": staged["payload"],
            "DATA_SDDL": DATA_FOLDER_SDDL,
            "AGENT_REMOVED": AGENT_REMOVED_CONDITION,
            "OLD_RUSTDESK": OLD_RUSTDESK_CONDITION,
        },
    )
    body = (
        body.replace("@SERVICE_COMPONENT@", service)
        .replace("@OLD_RUSTDESK_SEARCH@", old_rustdesk_search)
        .replace("@REMOVE_OLD_RUSTDESK@", remove_old_rustdesk)
        .replace("@UNINSTALL_ADDED@", uninstall_added)
    )
    return wix_build.package_source(
        name="Neutrino Agent",
        manufacturer=publisher,
        version=version,
        upgrade_code=UPGRADE_CODE,
        body=body,
    )


def _lay_out(root: Path, version: str, machine: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``amd64``.

    Returns:
        The paths the installer's source names: the payload directory, with
        RustDesk's files under its ``rustdesk``, and the agent's own binary,
        kept out of the payload so the service component can claim it.

    Raises:
        SystemExit: When this Python is not the pinned minor, when the
            machine asked for is not this one, when the compile writes no
            binary, or when RustDesk is not what was pinned.
    """
    _check_build_machine(machine)
    tree = root / "tree"
    payload.stage_agent_tree(tree, version)

    python = _make_build_environment(root / "venv")
    dist = _compile(python, tree, root / "build", version)

    installed = root / "payload"
    installed.mkdir(parents=True)
    for item in dist.iterdir():
        if item.name == AGENT_BINARY_NAME:
            continue
        if item.is_dir():
            shutil.copytree(item, installed / item.name)
        else:
            shutil.copyfile(item, installed / item.name)
    binary = root / AGENT_BINARY_NAME
    shutil.copyfile(dist / AGENT_BINARY_NAME, binary)
    _stage_licenses(installed)
    rustdesk_assets.stage_windows_files(installed / RUSTDESK_DIR_NAME)
    return {"payload": installed, "binary": binary}


def _check_build_machine(machine: str) -> None:
    """Refuse a build that would carry another interpreter than the pinned
    one, or one for a machine this is not.

    Args:
        machine: ``amd64``, as asked for.

    Raises:
        SystemExit: On either mismatch.
    """
    if sys.version_info[:2] != BUILD_PYTHON_VERSION:
        wanted = ".".join(str(part) for part in BUILD_PYTHON_VERSION)
        raise SystemExit(
            f"the agent is compiled against Python {wanted}; "
            f"this is {sys.version.split()[0]}"
        )
    here = WINDOWS_MACHINES.get(
        payload.MACHINE_NAMES.get(platform.machine().lower(), ""), ""
    )
    if here != machine:
        raise SystemExit(
            f"an installer for {machine} is compiled on a {machine} machine; "
            f"this one is {platform.machine()}"
        )


def _make_build_environment(venv: Path) -> Path:
    """A virtual environment holding the pinned compiler.

    Args:
        venv: Where to make it.

    Returns:
        The environment's interpreter.

    Raises:
        SystemExit: When pip refuses.
    """
    payload.run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "Scripts" / "python.exe"
    payload.run(nuitka_build.pip_install_command(python))
    return python


def _compile(python: Path, tree: Path, build: Path, version: str) -> Path:
    """Run Nuitka over the staged package into a console program.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_agent`` package is in.
        build: Where the compiler works.
        version: The version stamped into the binary's own properties.

    Returns:
        The standalone directory: the binary and everything beside it.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    return nuitka_build.compile_standalone(
        python,
        tree / "neutrino_agent" / "cli" / "entry.py",
        build,
        AGENT_BINARY_NAME,
        source_root=tree,
        options=(
            "--include-package=neutrino_agent",
            nuitka_build.NUITKA_ARGV_PASSTHROUGH,
            "--windows-console-mode=force",
            "--product-name=Neutrino Agent",
            f"--product-version={version}",
            f"--file-version={version}",
        ),
    )


def _stage_licenses(installed: Path) -> None:
    """Copy the licences of what the installer carries beside the payload.

    Args:
        installed: The directory the installer lays down whole.

    Raises:
        SystemExit: When a licence the package owes is not in the checkout.
    """
    destination = installed / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    for name in payload.CARRIED_LICENSES:
        source = REPO_ROOT / "licenses" / name
        if not source.is_file():
            raise SystemExit(
                f"the package carries {name} and there is none at {source}"
            )
        shutil.copyfile(source, destination / name)


def _check_tools(is_stage_only: bool) -> None:
    """Refuse to start on a machine that cannot finish the build.

    Args:
        is_stage_only: Whether the build stops before wix.

    Raises:
        SystemExit: When this is not Windows, the decompressor RustDesk's
            files need is not installed, or WiX is missing.
    """
    if sys.platform != "win32":
        raise SystemExit(f"{Path(__file__).name} runs on Windows; this is {sys.platform}")
    if importlib.util.find_spec(rustdesk_assets.RUSTDESK_PACKED_DECOMPRESSOR) is None:
        raise SystemExit(
            "unpacking RustDesk's Windows files needs the Python package "
            f"{rustdesk_assets.RUSTDESK_PACKED_DECOMPRESSOR}: pip install "
            f"{rustdesk_assets.RUSTDESK_PACKED_DECOMPRESSOR}=="
            f"{rustdesk_assets.RUSTDESK_PACKED_DECOMPRESSOR_VERSION}"
        )
    if not is_stage_only and shutil.which("wix") is None:
        raise SystemExit(
            "WiX 6 is needed and wix is not on the path: "
            "dotnet tool install --global wix --version 6.0.2"
        )


if __name__ == "__main__":
    raise SystemExit(main())
