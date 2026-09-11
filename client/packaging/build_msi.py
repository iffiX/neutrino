"""Build the client's Windows installer.

    python client/packaging/build_msi.py --output-dir dist/ --architecture x64

The installer carries its own Python. Windows ships none, and the client
lands on machines nobody has prepared, so the interpreter is python.org's
embeddable build, pinned by hash, with the window's whole Python side
vendored beside it.

The client is a person's application, not a service and not an autostart: it
runs when the person opens it. The installer puts a Start menu shortcut down
and asks two questions: whether the command belongs on PATH, and, when it is
taking the client away again, whether the person's own configuration goes
with it. Answered by nobody, the first is yes and the second is no, so a
silent install is usable from a terminal and a silent removal leaves a
binding behind rather than losing one.

The client's services last only as long as it runs, so an upgrade or a
removal asks the resident to quit before it takes its files. That quit runs
through the Util extension's quiet exec, which opens no console window for
it.

WebView2 is the one thing the machine may still lack. Windows 11 and any
updated Windows 10 carry the Evergreen runtime; LTSC and Server editions do
not, so Microsoft's bootstrapper travels in the package and runs when the
runtime's registry key is absent.

Needs WiX 6: ``dotnet tool install --global wix --version 6.0.2``, and its
Util extension: ``wix extension add -g WixToolset.Util.wixext/6.0.2``. WiX 7
refuses to build until a maintenance-fee EULA is accepted, and the
extension's own 7 does not load in 6.

Not pure: downloads an interpreter and wheels, writes a package tree, runs wix.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.sax.saxutils
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bundled  # noqa: E402
import icons  # noqa: E402
import payload  # noqa: E402

CLIENT_ROOT = payload.CLIENT_ROOT
REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the installer carries, one build per machine. Pinned by
# hash: a package that installs an unverified interpreter is not one to ship.
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

# The image a running resident wears in the process list. The window runs
# under the carried interpreter, so that is the name an install must close.
RESIDENT_IMAGE = "pythonw.exe"

# The person's own configuration, named the way the runtime names it. The
# installer never writes here; it only offers to take it away at the end.
CLIENT_CONFIG_DIR_NAME = "Neutrino Client"

# The extensions this source needs, at the version this WiX loads: Util for
# CloseApplication and the quiet exec, UI for the dialogs the two questions
# are asked on.
WIX_UTIL_EXTENSION = "WixToolset.Util.wixext/6.0.2"
WIX_UI_EXTENSION = "WixToolset.UI.wixext/6.0.2"

# The library the Util extension keeps its custom actions in, one per
# machine. The removal below is declared against it rather than carrying a
# program of its own.
UTIL_LIBRARY = {"amd64": "Wix4UtilCA_X64", "arm64": "Wix4UtilCA_A64"}

# The identity of the product across every version it ever ships as. Fixed:
# changing it makes an upgrade install beside the old one instead of over it.
UPGRADE_CODE = "0221A508-0A7E-4CFE-B517-B901D9318962"

CONSOLE_WRAPPER_NAME = "nclient.cmd"
CONSOLE_WRAPPER = """@echo off
rem Run the client in a terminal, for `nclient status` and for reading errors.
"%~dp0python\\python.exe" -m neutrino_client.cli.entry %*
"""

# The quit, run as the person installing. Through the windowed interpreter
# rather than the console one: an installer's custom action gets a console of
# its own for a console program, and that console opens as a black window
# over the wizard. The ask itself is bounded by the control socket's own
# timeout, so nothing here has to time it out.
#
# `-B` because this one runs during a removal, after the files to take have
# been counted: bytecode written now lands in a prefix on its way out, too
# late to have been counted with it.
QUIT_COMMAND = (
    '"[INSTALLFOLDER]python\\pythonw.exe" -B -m neutrino_client.cli.entry quit'
)

# When the configuration goes. Unticking the box clears the property, and a
# silent removal may set it to anything; what it is never equal to then is
# the one value that means keep. `NOT ISCONFIGKEPT` would not do: a property
# set to "0" is a non-empty string, and the installer reads every non-empty
# string as true.
CONFIG_GOES_CONDITION = 'REMOVE~="ALL" AND ISCONFIGKEPT <> "1"'

# The same reading for the entry on PATH: what a silent install says when it
# wants none.
PATH_DECLINED_CONDITION = 'ISPATHADDED <> "1"'

# Taking the person's configuration away, when they said to. The path is
# expanded while the installer still runs as them; the removal itself runs
# without an account, so the expanded path travels to it as data.
REMOVE_CONFIG_COMMAND = (
    '"[SystemFolder]cmd.exe" /c ' f'rd /s /q "[AppDataFolder]{CLIENT_CONFIG_DIR_NAME}"'
)

# @NAME@ rather than str.format: the source is XML with braces of its own in
# the property expressions.
WIX_SOURCE = r"""<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs"
     xmlns:ui="http://wixtoolset.org/schemas/v4/wxs/ui"
     xmlns:util="http://wixtoolset.org/schemas/v4/wxs/util">
  <Package Name="Neutrino Client"
           Manufacturer="@PUBLISHER@"
           Version="@VERSION@"
           UpgradeCode="@UPGRADE_CODE@"
           Scope="perMachine"
           Compressed="yes">
    <MajorUpgrade AllowSameVersionUpgrades="yes"
                  DowngradeErrorMessage="A newer Neutrino Client is already installed." />
    <MediaTemplate EmbedCab="yes" />

    <!-- The two questions, and the answers nobody being there gives: a
         silent install puts the command on PATH, and a silent removal keeps
         the person's own configuration. -->
    <Property Id="ISPATHADDED" Value="1" Secure="yes" />
    <Property Id="ISCONFIGKEPT" Value="1" Secure="yes" />

    <ui:WixUI Id="WixUI_InstallDir" InstallDirectory="INSTALLFOLDER" />
    <WixVariable Id="WixUILicenseRtf" Value="@LICENSE_RTF@" />

    <!-- The client's services live only as long as the resident does, so it
         is asked to quit before its files are replaced or taken away. No
         resident to answer is not a failed install. -->
    <CustomAction Id="QuitClientResident"
                  Directory="INSTALLFOLDER"
                  ExeCommand="@QUIT_COMMAND@"
                  Execute="immediate"
                  Return="ignore" />

    <!-- What still holds the install's files once the quit is done, and what
         makes an upgrade land half-applied, so it is closed and then ended. -->
    <util:CloseApplication Id="CloseClientWindow"
                           Target="@RESIDENT_IMAGE@"
                           CloseMessage="yes"
                           EndSessionMessage="yes"
                           TerminateProcess="0"
                           RebootPrompt="no"
                           Property="CLIENTWINDOWRUNNING" />
    <Icon Id="ClientIcon" SourceFile="@ICON@" />
    <Property Id="ARPPRODUCTICON" Value="ClientIcon" />

    <!-- Read before costing, which is earlier than the prefix resolving, so
         the removal above has a path at the moment it needs one. -->
    <Property Id="NEUTRINOINSTALLDIR" Secure="yes">
      <RegistrySearch Id="ClientInstallDir"
                      Root="HKLM"
                      Key="Software\Neutrino\Client"
                      Name="InstallDir"
                      Type="directory" />
    </Property>

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
      <Directory Id="INSTALLFOLDER" Name="Neutrino Client" />
    </StandardDirectory>
    <StandardDirectory Id="ProgramMenuFolder" />

    <ComponentGroup Id="Payload" Directory="INSTALLFOLDER">
      <Files Include="@PAYLOAD@\**" />
      <Component Id="WebView2Bootstrapper" Guid="*">
        <File Id="WebView2BootstrapperExe"
              Source="@BOOTSTRAPPER@"
              Name="@BOOTSTRAPPER_NAME@"
              KeyPath="yes" />
      </Component>
      <!-- The prefix, whatever ended up in it. The carried interpreter
           writes its bytecode beside the modules it runs, and a file the
           install never laid down is one the uninstall does not know to
           take; the path is recorded so the removal can still find it. -->
      <Component Id="InstallFolderRecord" Guid="*">
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Client"
                       Name="InstallDir"
                       Type="string"
                       Value="[INSTALLFOLDER]"
                       KeyPath="yes" />
        <util:RemoveFolderEx Id="PruneInstallFolder"
                             On="uninstall"
                             Property="NEUTRINOINSTALLDIR" />
      </Component>
      <Component Id="StartMenuShortcut" Guid="*">
        <Shortcut Id="ClientWindowShortcut"
                  Directory="ProgramMenuFolder"
                  Name="Neutrino Client"
                  Description="Use the services a Neutrino Hub publishes for you"
                  Target="[INSTALLFOLDER]python\pythonw.exe"
                  Arguments="-m neutrino_client.cli.entry gui"
                  WorkingDirectory="INSTALLFOLDER"
                  Icon="ClientIcon" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Client"
                       Name="Shortcut"
                       Type="integer"
                       Value="1"
                       KeyPath="yes" />
      </Component>
    </ComponentGroup>

    <!-- Its own feature rather than a conditioned component: a feature's
         state is what the installer remembers between putting the entry
         there and taking it away again. -->
    <ComponentGroup Id="PathOption" Directory="INSTALLFOLDER">
      <Component Id="PathEntry" Guid="*">
        <Environment Id="ClientPath"
                     Name="PATH"
                     Value="[INSTALLFOLDER]"
                     Part="last"
                     Action="set"
                     System="yes" />
        <RegistryValue Root="HKLM"
                       Key="Software\Neutrino\Client"
                       Name="Path"
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

    <!-- The configuration, when the person said to take it. The path is
         expanded while the installer is still them; the removal runs with no
         account at all, so the expanded path reaches it as data. -->
    <CustomAction Id="SetRemoveClientConfig"
                  Property="RemoveClientConfig"
                  Value="@REMOVE_CONFIG_COMMAND@"
                  Execute="immediate" />
    <CustomAction Id="RemoveClientConfig"
                  DllEntry="WixQuietExec"
                  BinaryRef="@UTIL_LIBRARY@"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore" />

    <InstallExecuteSequence>
      <!-- After costing, which resolves [INSTALLFOLDER], and before the
           extension's own close, which it schedules on InstallInitialize. -->
      <Custom Action="QuitClientResident"
              After="CostFinalize"
              Condition="Installed OR WIX_UPGRADE_DETECTED" />
      <Custom Action="InstallWebView2"
              After="InstallFiles"
              Condition="NOT WEBVIEW2INSTALLED AND NOT REMOVE" />
      <Custom Action="SetRemoveClientConfig"
              Before="RemoveClientConfig"
              Condition="@CONFIG_GOES@" />
      <Custom Action="RemoveClientConfig"
              After="RemoveFiles"
              Condition="@CONFIG_GOES@" />
    </InstallExecuteSequence>

    <Feature Id="Main" Title="Neutrino Client" Level="1" AllowAbsent="no">
      <ComponentGroupRef Id="Payload" />
    </Feature>
    <Feature Id="PathFeature"
             Title="Command line"
             Description="Answer to nclient in a terminal"
             Level="1">
      <!-- The wizard drives this feature from its checkbox; the level is
           what makes the same answer reachable from a silent install. -->
      <Level Value="0" Condition="@PATH_DECLINED@" />
      <ComponentGroupRef Id="PathOption" />
    </Feature>

    <UI>
      <!-- Asked on the way in: whether the command belongs on PATH. -->
      <Dialog Id="ClientOptionsDlg" Width="370" Height="270" Title="[ProductName] Setup">
        <Control Id="BannerBitmap" Type="Bitmap" X="0" Y="0" Width="370" Height="44"
                 TabSkip="no" Text="!(loc.InstallDirDlgBannerBitmap)" />
        <Control Id="BannerLine" Type="Line" X="0" Y="44" Width="370" Height="0" />
        <Control Id="Title" Type="Text" X="15" Y="6" Width="230" Height="15"
                 Transparent="yes" NoPrefix="yes"
                 Text="{\WixUI_Font_Title}The command line" />
        <Control Id="Description" Type="Text" X="25" Y="23" Width="330" Height="15"
                 Transparent="yes" NoPrefix="yes"
                 Text="Whether a terminal on this machine answers to nclient." />
        <Control Id="PathCheckBox" Type="CheckBox" X="20" Y="70" Width="330" Height="17"
                 Property="ISPATHADDED" CheckBoxValue="1"
                 Text="Add the Neutrino Client to PATH" />
        <Control Id="PathNote" Type="Text" X="34" Y="90" Width="320" Height="40"
                 NoPrefix="yes"
                 Text="This changes the PATH every account on this machine reads. Without it the client still installs, opens and runs; only the nclient command goes unfound." />
        <Control Id="BottomLine" Type="Line" X="0" Y="234" Width="370" Height="0" />
        <Control Id="Back" Type="PushButton" X="180" Y="243" Width="56" Height="17"
                 Text="!(loc.WixUIBack)" />
        <Control Id="Next" Type="PushButton" X="236" Y="243" Width="56" Height="17"
                 Default="yes" Text="!(loc.WixUINext)" />
        <Control Id="Cancel" Type="PushButton" X="304" Y="243" Width="56" Height="17"
                 Cancel="yes" Text="!(loc.WixUICancel)" />
      </Dialog>

      <!-- Asked on the way out: whether the configuration stays behind. -->
      <Dialog Id="ClientRemoveDlg" Width="370" Height="270" Title="[ProductName] Setup">
        <Control Id="BannerBitmap" Type="Bitmap" X="0" Y="0" Width="370" Height="44"
                 TabSkip="no" Text="!(loc.InstallDirDlgBannerBitmap)" />
        <Control Id="BannerLine" Type="Line" X="0" Y="44" Width="370" Height="0" />
        <Control Id="Title" Type="Text" X="15" Y="6" Width="230" Height="15"
                 Transparent="yes" NoPrefix="yes"
                 Text="{\WixUI_Font_Title}Your configuration" />
        <Control Id="Description" Type="Text" X="25" Y="23" Width="330" Height="15"
                 Transparent="yes" NoPrefix="yes"
                 Text="What stays on this machine after the client is gone." />
        <Control Id="ConfigCheckBox" Type="CheckBox" X="20" Y="70" Width="330" Height="17"
                 Property="ISCONFIGKEPT" CheckBoxValue="1"
                 Text="Keep my configuration" />
        <Control Id="ConfigNote" Type="Text" X="34" Y="90" Width="320" Height="40"
                 NoPrefix="yes"
                 Text="The hub this machine is joined to and the preferences of the window, under %APPDATA%\Neutrino Client. Kept, installing the client again joins the same hub without a new link." />
        <Control Id="BottomLine" Type="Line" X="0" Y="234" Width="370" Height="0" />
        <Control Id="Back" Type="PushButton" X="180" Y="243" Width="56" Height="17"
                 Text="!(loc.WixUIBack)" />
        <Control Id="Next" Type="PushButton" X="236" Y="243" Width="56" Height="17"
                 Default="yes" Text="!(loc.WixUINext)" />
        <Control Id="Cancel" Type="PushButton" X="304" Y="243" Width="56" Height="17"
                 Cancel="yes" Text="!(loc.WixUICancel)" />
      </Dialog>

      <!-- Both dialogs are inserted into the set rather than replacing it, so
           the orders here sit above the ones the set publishes itself. -->
      <Publish Dialog="InstallDirDlg" Control="Next" Event="NewDialog"
               Value="ClientOptionsDlg" Order="10" />
      <Publish Dialog="ClientOptionsDlg" Control="Back" Event="NewDialog"
               Value="InstallDirDlg" />
      <Publish Dialog="ClientOptionsDlg" Control="Next" Event="AddLocal"
               Value="PathFeature" Order="1" Condition="ISPATHADDED" />
      <Publish Dialog="ClientOptionsDlg" Control="Next" Event="Remove"
               Value="PathFeature" Order="1" Condition="NOT ISPATHADDED" />
      <Publish Dialog="ClientOptionsDlg" Control="Next" Event="NewDialog"
               Value="VerifyReadyDlg" Order="2" />
      <Publish Dialog="ClientOptionsDlg" Control="Cancel" Event="SpawnDialog"
               Value="CancelDlg" />

      <Publish Dialog="MaintenanceTypeDlg" Control="RemoveButton" Event="NewDialog"
               Value="ClientRemoveDlg" Order="10" />
      <Publish Dialog="ClientRemoveDlg" Control="Back" Event="NewDialog"
               Value="MaintenanceTypeDlg" />
      <Publish Dialog="ClientRemoveDlg" Control="Next" Event="NewDialog"
               Value="VerifyReadyDlg" />
      <Publish Dialog="ClientRemoveDlg" Control="Cancel" Event="SpawnDialog"
               Value="CancelDlg" />

      <Publish Dialog="VerifyReadyDlg" Control="Back" Event="NewDialog"
               Value="ClientOptionsDlg" Order="10"
               Condition="WixUI_InstallMode = &quot;InstallCustom&quot;" />
      <Publish Dialog="VerifyReadyDlg" Control="Back" Event="NewDialog"
               Value="ClientRemoveDlg" Order="11"
               Condition="WixUI_InstallMode = &quot;Remove&quot;" />
    </UI>
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
    # The OS in the name: nothing about `.msi` says Windows to a release page
    # listing five platforms.
    target = output_dir / f"{PACKAGE_NAME}-{version}-windows-{machine}.msi"

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = _lay_out(root, version, machine, arguments.architecture)
        source = root / "neutrino_client.wxs"
        source.write_text(
            _wix_source(staged, version, arguments.publisher, machine), "utf-8"
        )
        if arguments.stage_only:
            print(f"staged {staged['payload']} and {source}")
            return 0
        _build(source, target, machine)

    if not target.is_file():
        raise SystemExit(f"wix wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _wix_source(staged: dict, version: str, publisher: str, machine: str) -> str:
    """The installer's source with every value filled in.

    Args:
        staged: What :func:`_lay_out` wrote.
        version: The version being packaged.
        publisher: The Manufacturer field's value.
        machine: ``amd64`` or ``arm64``, which picks the extension's own
            pieces.

    Returns:
        The .wxs document.
    """
    return (
        WIX_SOURCE.replace("@VERSION@", version)
        # Every value lands inside a double-quoted XML attribute; a publisher
        # with an address in angle brackets, or a command line that quotes its
        # own path, is plain text there and must not become markup.
        .replace("@PUBLISHER@", _attribute_text(publisher))
        .replace("@UPGRADE_CODE@", UPGRADE_CODE)
        .replace("@PAYLOAD@", str(staged["payload"]))
        .replace("@BOOTSTRAPPER@", str(staged["bootstrapper"]))
        .replace("@BOOTSTRAPPER_NAME@", WEBVIEW2_BOOTSTRAPPER_NAME)
        .replace("@ICON@", str(staged["icon"]))
        .replace("@WEBVIEW2_KEY@", WEBVIEW2_REGISTRY_KEY)
        .replace("@RESIDENT_IMAGE@", RESIDENT_IMAGE)
        .replace("@LICENSE_RTF@", str(staged["license"]))
        .replace("@UTIL_LIBRARY@", UTIL_LIBRARY[machine])
        .replace("@QUIT_COMMAND@", _attribute_text(QUIT_COMMAND))
        .replace("@REMOVE_CONFIG_COMMAND@", _attribute_text(REMOVE_CONFIG_COMMAND))
        .replace("@CONFIG_GOES@", _attribute_text(CONFIG_GOES_CONDITION))
        .replace("@PATH_DECLINED@", _attribute_text(PATH_DECLINED_CONDITION))
    )


def _attribute_text(value: str) -> str:
    """Text safe inside a double-quoted XML attribute."""
    return xml.sax.saxutils.escape(value, {'"': "&quot;"})


def _lay_out(root: Path, version: str, machine: str, architecture: str) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``amd64`` or ``arm64``.
        architecture: The architecture as the command line named it.

    Returns:
        The paths the installer's source names: the payload directory, the
        bootstrapper, the icon and the licence the first page shows.
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

    payload.stage_client_tree(installed, version)
    payload.stage_wheels(
        Path(sys.executable),
        installed / "lib",
        WINDOWS_WHEELS + (WINDOWS_CFFI[machine],),
        platform_tag=f"win_{machine}",
        abi_tag=WINDOWS_PYTHON_ABI,
    )
    bundled.stage_windows_binaries(installed, architecture)
    _stage_licenses(installed)
    (installed / CONSOLE_WRAPPER_NAME).write_text(CONSOLE_WRAPPER, encoding="utf-8")

    # Named files the installer's source points at directly, kept out of the
    # payload directory so the file glob does not claim them twice.
    bootstrapper = root / WEBVIEW2_BOOTSTRAPPER_NAME
    bootstrapper.write_bytes(_fetch_bootstrapper())
    icon = icons.write_ico(root / "neutrino_client.ico")
    license_rtf = _write_license_rtf(root / "license.rtf")
    return {
        "payload": installed,
        "bootstrapper": bootstrapper,
        "icon": icon,
        "license": license_rtf,
    }


def _write_license_rtf(target: Path) -> Path:
    """Write the project's licence as the rich text the first page reads.

    The wizard's licence control takes RTF and nothing else, and the licence
    in the checkout is plain text, so the one in the repository stays the
    only copy and this is its wrapper.

    Args:
        target: Where to write it.

    Returns:
        The path written.

    Raises:
        SystemExit: When the checkout has no licence to show.
    """
    source = REPO_ROOT / "LICENSE"
    if not source.is_file():
        raise SystemExit(f"the installer shows a licence and there is none at {source}")
    body = source.read_text(encoding="utf-8")
    for character, escaped in (("\\", "\\\\"), ("{", "\\{"), ("}", "\\}")):
        body = body.replace(character, escaped)
    paragraphs = "\\par\n".join(body.splitlines())
    target.write_text(
        "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0\\fnil\\fcharset0 Segoe UI;}}\n"
        "\\fs18\n" + paragraphs + "\n}\n",
        encoding="ascii",
        errors="replace",
    )
    return target


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


def _fetch_bootstrapper() -> bytes:
    """Download Microsoft's WebView2 bootstrapper.

    Returns:
        The installer's bytes.

    Raises:
        SystemExit: When what arrives is not a Windows executable, or is not
            the size one is.
    """
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
    """Let the bundled interpreter see the client and the vendored packages.

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
            "dotnet tool install --global wix --version 6.0.2 && "
            f"wix extension add -g {WIX_UTIL_EXTENSION} && "
            f"wix extension add -g {WIX_UI_EXTENSION}"
        )
    result = subprocess.run(
        [
            wix,
            "build",
            "-arch",
            MSI_PLATFORMS[machine],
            "-ext",
            WIX_UTIL_EXTENSION,
            "-ext",
            WIX_UI_EXTENSION,
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
