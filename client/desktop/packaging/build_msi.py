"""Build the client's Windows installer.

    python client/desktop/packaging/build_msi.py --output-dir dist/ --architecture x64 \
        --packet-dll build/packet_stub/packet.dll

The installer carries the client compiled: Nuitka turns the package, the
interpreter it runs on and the window's Python side into ``nclient.exe`` for
a terminal and ``nclientw.exe`` for the shortcut, with the libraries beside
them. Windows ships no Python and the client lands on
machines nobody has prepared, so a carried interpreter was the alternative,
and a tree of ``.pyc`` files and a ``python313.zip`` is what heuristic
scanners flag; fifty-one files with no bytecode among them is what they do
not. The interpreter compiled in is the one running this script, so the
build machine's Python is pinned to a minor here and checked.

The client is a person's application, not a service and not an autostart: it
runs when the person opens it. The two overlay daemons it carries are
services that start with Windows: NetBird's, and the client's own EasyTier
daemon, ``nclient.exe easytier-daemon --service`` as SYSTEM, which runs
EasyTier's core as its child only while a network or a console is
configured. Beside EasyTier's core and CLI ride wintun.dll and a stand-in
packet.dll: the core does not start without a Packet.dll to load, Npcap's
may not be carried, and the stand-in, built from ``packet_stub.c`` beside
this file with MSVC before this script runs, exports the functions the core
imports and answers failure from each. The build refuses to package without
it. The installer puts a Start menu shortcut down
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
Util and UI extensions: ``wix extension add -g WixToolset.Util.wixext/6.0.2``
and the same for ``WixToolset.UI.wixext``. WiX 7 refuses to build until a
maintenance-fee EULA is accepted, and the extension's own 7 does not load in
6. Nuitka needs a C compiler and fetches MinGW-w64 itself when there is
none; the build is native, so an arm64 installer is built on an arm64
machine.

Not pure: makes a virtual environment, downloads wheels and a compiler,
compiles, writes a package tree, runs wix.
"""

import argparse
import platform
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))
import bundled  # noqa: E402
import icons  # noqa: E402
from shared import nuitka_build  # noqa: E402
import payload  # noqa: E402
from shared import wix_build  # noqa: E402

# The service names and the portal are the client's own, named here so the
# installer and the runtime cannot drift.
from neutrino_client.constants import (  # noqa: E402
    CLIENT_EASYTIER_DAEMON_VERB,
    CLIENT_EASYTIER_SERVICE_WINDOWS,
    CLIENT_NETBIRD_SERVICE_WINDOWS,
)

CLIENT_ROOT = payload.CLIENT_ROOT
REPO_ROOT = payload.REPO_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The interpreter the client is compiled against is the one running this
# script, so it is what the installer carries. One minor, checked, so a build
# machine with another does not quietly ship a different Python.
BUILD_PYTHON_VERSION = (3, 13)

# The compiled client, twice: one executable is a console program, for a
# terminal, a script, a pipe or a shell with no console of its own, all of
# which hand it their standard handles; the other is a windowed program, for
# the shortcut and the installer, neither of which may open a console. One
# executable cannot be both: a windowed one started with pipes but no console
# loses the pipes, and a console one started from a shortcut opens a window.
# The same split python.exe and pythonw.exe make.
CLIENT_BINARY_NAME = "nclient.exe"
CLIENT_WINDOWED_BINARY_NAME = "nclientw.exe"

# The window backends pywebview carries for other platforms. Nuitka's own
# pywebview plugin leaves them out; naming them here is what keeps a
# following of the package from disagreeing with it.
NUITKA_EXCLUDED_BACKENDS = (
    "webview.platforms.android",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
)

# What each name for the machine maps to in the wheel's own naming.
WINDOWS_MACHINES = {"x86_64": "amd64", "aarch64": "arm64"}

# The window's Python side, pinned to the file and compiled in. pywebview
# drives the WebView2 control through pythonnet, which reaches .NET through
# clr-loader and cffi; the rest is what pywebview itself imports.
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

# The person's own configuration, named the way the runtime names it. The
# installer never writes here; it only offers to take it away at the end.
CLIENT_CONFIG_DIR_NAME = "Neutrino Client"

# The identity of the product across every version it ever ships as. Fixed:
# changing it makes an upgrade install beside the old one instead of over it.
UPGRADE_CODE = "0221A508-0A7E-4CFE-B517-B901D9318962"

# The quit, run as the person installing, through the windowed program: an
# installer's custom action has no console, and a console program started by
# one opens a black window over the wizard. The ask itself is bounded by the
# control socket's own timeout, so nothing here has to time it out.
QUIT_COMMAND = f'"[INSTALLFOLDER]{CLIENT_WINDOWED_BINARY_NAME}" quit'

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

# The stand-in for Npcap's Packet.dll, as it lands beside easytier-core.exe.
PACKET_DLL_NAME = "packet.dll"

# NetBird's binary under the payload's bin and how its service runs, its
# state under ProgramData; the EasyTier daemon is the console program run
# with its verb, and makes its own state directory under ProgramData.
NETBIRD_EXE = "netbird.exe"
NETBIRD_SERVICE_ARGUMENTS = (
    'service run --config "[CommonAppDataFolder]Neutrino Client\\netbird\\config.json"'
    ' --log-file "[CommonAppDataFolder]Neutrino Client\\netbird\\client.log"'
)
EASYTIER_DAEMON_ARGUMENTS = f"{CLIENT_EASYTIER_DAEMON_VERB} --service"
# What the service control manager does when the EasyTier daemon ends without
# being stopped: start it again, as the agent's service does.
EASYTIER_DAEMON_RECOVERY = (
    '<util:ServiceConfig FirstFailureActionType="restart" '
    'SecondFailureActionType="restart" ThirdFailureActionType="restart" '
    'RestartServiceDelayInSeconds="10" ResetPeriodInDays="1" />'
)

# The package's body, inside the Package element wix_build writes around it.
# @NAME@ rather than str.format: the source is XML with braces of its own in
# the property expressions.
WIX_BODY = r"""
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
         makes an upgrade land half-applied, so it is closed and then ended:
         a resident from the shortcut, or one from a terminal. -->
    <util:CloseApplication Id="CloseClientWindow"
                           Target="@RESIDENT_IMAGE_WINDOWED@"
                           CloseMessage="yes"
                           EndSessionMessage="yes"
                           TerminateProcess="0"
                           RebootPrompt="no"
                           Property="CLIENTWINDOWRUNNING" />
    <util:CloseApplication Id="CloseClientConsole"
                           Target="@RESIDENT_IMAGE_CONSOLE@"
                           CloseMessage="yes"
                           EndSessionMessage="yes"
                           TerminateProcess="0"
                           RebootPrompt="no"
                           Property="CLIENTCONSOLERUNNING" />
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

    <StandardDirectory Id="CommonAppDataFolder">
      <Directory Id="CLIENTDATAFOLDER" Name="Neutrino Client">
        <Directory Id="NETBIRDDATAFOLDER" Name="netbird" />
      </Directory>
    </StandardDirectory>

    <ComponentGroup Id="Payload" Directory="INSTALLFOLDER">
      <!-- The two daemons' binaries are the service components below, not
           files of the glob. -->
      <Files Include="@PAYLOAD@\**">
        <Exclude Files="@NETBIRD_EXE@" />
        <Exclude Files="@CLIENT_EXE@" />
      </Files>
      <Component Id="WebView2Bootstrapper" Guid="*">
        <File Id="WebView2BootstrapperExe"
              Source="@BOOTSTRAPPER@"
              Name="@BOOTSTRAPPER_NAME@"
              KeyPath="yes" />
      </Component>
      <!-- The prefix, whatever ended up in it: a file the install never
           laid down is one the uninstall does not know to take, and the
           path is recorded so the removal can still find it. -->
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
                  Target="[INSTALLFOLDER]@CLIENT_WINDOWED_BINARY@"
                  Arguments="gui"
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

@DAEMONS@

    <Feature Id="Main" Title="Neutrino Client" Level="1" AllowAbsent="no">
      <ComponentGroupRef Id="Payload" />
      <ComponentGroupRef Id="Daemons" />
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
    parser.add_argument(
        "--packet-dll",
        default="",
        help="the stand-in packet.dll built from packet_stub.c",
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
        staged = _lay_out(
            root,
            version,
            machine,
            arguments.architecture,
            packet_dll=Path(arguments.packet_dll) if arguments.packet_dll else None,
        )
        source = root / "neutrino_client.wxs"
        source.write_text(
            _wix_source(staged, version, arguments.publisher, machine), "utf-8"
        )
        if arguments.stage_only:
            print(f"staged {staged['payload']} and {source}")
            return 0
        wix_build.build(source, target, machine)

    if not target.is_file():
        raise SystemExit(f"wix wrote no {target.name}")
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def daemons_source(payload_dir: Path) -> str:
    """The two overlay daemons as services, and the folder NetBird's state is in.

    Args:
        payload_dir: The staged payload: ``bin`` holds NetBird, and the
            console client, which is the EasyTier daemon, is at its top.

    Returns:
        The ``Daemons`` component group.
    """
    netbird = wix_build.element(
        "Component",
        {"Id": "NetbirdService", "Guid": "*", "Subdirectory": "bin"},
        (
            wix_build.element(
                "File",
                {
                    "Id": "NetbirdServiceFile",
                    "Source": str(payload_dir / "bin" / NETBIRD_EXE),
                    "KeyPath": "yes",
                },
            ),
            wix_build.element(
                "ServiceInstall",
                {
                    "Id": "NetbirdServiceInstall",
                    "Name": CLIENT_NETBIRD_SERVICE_WINDOWS,
                    "DisplayName": "Neutrino Client NetBird",
                    "Description": "The NetBird daemon the Neutrino client joins with",
                    "Type": "ownProcess",
                    "Start": "auto",
                    "ErrorControl": "normal",
                    "Account": "LocalSystem",
                    "Arguments": NETBIRD_SERVICE_ARGUMENTS,
                },
            ),
            wix_build.element(
                "ServiceControl",
                {
                    "Id": "NetbirdServiceControl",
                    "Name": CLIENT_NETBIRD_SERVICE_WINDOWS,
                    "Start": "install",
                    "Stop": "both",
                    "Remove": "uninstall",
                    "Wait": "no",
                },
            ),
        ),
    )
    easytier = wix_build.service_component(
        component_id="EasytierDaemon",
        source=payload_dir / CLIENT_BINARY_NAME,
        service_name=CLIENT_EASYTIER_SERVICE_WINDOWS,
        display_name="Neutrino Client EasyTier",
        description="The daemon that runs EasyTier for the Neutrino client",
        arguments=EASYTIER_DAEMON_ARGUMENTS,
        permissions=(EASYTIER_DAEMON_RECOVERY,),
    )
    folder = wix_build.element(
        "Component",
        {"Id": "NetbirdDataFolder", "Guid": "*", "Directory": "NETBIRDDATAFOLDER"},
        (
            wix_build.element("CreateFolder", {}),
            wix_build.element(
                "RegistryValue",
                {
                    "Root": "HKLM",
                    "Key": "Software\\Neutrino\\Client",
                    "Name": "NetbirdDataFolder",
                    "Type": "integer",
                    "Value": "1",
                    "KeyPath": "yes",
                },
            ),
        ),
    )
    return wix_build.element(
        "ComponentGroup",
        {"Id": "Daemons", "Directory": "INSTALLFOLDER"},
        (netbird, easytier, folder),
    )


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
    body = wix_build.fill(
        WIX_BODY,
        {
            "PAYLOAD": staged["payload"],
            "BOOTSTRAPPER": staged["bootstrapper"],
            "BOOTSTRAPPER_NAME": WEBVIEW2_BOOTSTRAPPER_NAME,
            "ICON": staged["icon"],
            "WEBVIEW2_KEY": WEBVIEW2_REGISTRY_KEY,
            "RESIDENT_IMAGE_WINDOWED": CLIENT_WINDOWED_BINARY_NAME,
            "RESIDENT_IMAGE_CONSOLE": CLIENT_BINARY_NAME,
            "CLIENT_WINDOWED_BINARY": CLIENT_WINDOWED_BINARY_NAME,
            "LICENSE_RTF": staged["license"],
            "UTIL_LIBRARY": wix_build.UTIL_LIBRARY[machine],
            "QUIT_COMMAND": QUIT_COMMAND,
            "REMOVE_CONFIG_COMMAND": REMOVE_CONFIG_COMMAND,
            "CONFIG_GOES": CONFIG_GOES_CONDITION,
            "PATH_DECLINED": PATH_DECLINED_CONDITION,
            "NETBIRD_EXE": Path(staged["payload"]) / "bin" / NETBIRD_EXE,
            "CLIENT_EXE": Path(staged["payload"]) / CLIENT_BINARY_NAME,
        },
    ).replace("@DAEMONS@", daemons_source(Path(staged["payload"])))
    return wix_build.package_source(
        name="Neutrino Client",
        manufacturer=publisher,
        version=version,
        upgrade_code=UPGRADE_CODE,
        body=body,
    )


def _lay_out(
    root: Path,
    version: str,
    machine: str,
    architecture: str,
    *,
    packet_dll: "Path | None",
) -> dict:
    """Write everything the installer carries.

    Args:
        root: The working directory to build under.
        version: The version being packaged.
        machine: ``amd64`` or ``arm64``.
        architecture: The architecture as the command line named it.
        packet_dll: The stand-in packet.dll; None refuses the build.

    Returns:
        The paths the installer's source names: the payload directory, the
        bootstrapper, the icon and the licence the first page shows.

    Raises:
        SystemExit: When there is no stand-in packet.dll, this Python is
            not the pinned minor, the machine asked for is not this one, or
            the compile writes no binary.
    """
    _check_packet_dll(packet_dll)
    _check_build_machine(machine)
    installed = root / "payload"
    installed.mkdir(parents=True)

    # The package with its version stamped and its page beside it, which is
    # what the compiler is pointed at; the checkout itself is never what
    # ships.
    tree = root / "tree"
    package = payload.stage_client_tree(tree, version)

    python = _make_build_environment(root / "venv", machine)
    dist = _compile(python, tree, root / "build", version)
    for item in dist.iterdir():
        if item.is_dir():
            shutil.copytree(item, installed / item.name)
        else:
            shutil.copyfile(item, installed / item.name)
    # Compiled modules keep a __file__ under the payload, so the package's
    # own data goes beside where that points.
    shutil.copytree(package / "data", installed / package.name / "data")

    bundled.stage_windows_binaries(installed, architecture)
    shutil.copyfile(packet_dll, installed / "bin" / PACKET_DLL_NAME)
    _stage_licenses(installed)

    # Named files the installer's source points at directly, kept out of the
    # payload directory so the file glob does not claim them twice.
    bootstrapper = root / WEBVIEW2_BOOTSTRAPPER_NAME
    bootstrapper.write_bytes(_fetch_bootstrapper())
    icon = icons.write_ico(root / "neutrino_client.ico")
    license_rtf = wix_build.write_license_rtf(
        REPO_ROOT / "LICENSE", root / "license.rtf"
    )
    return {
        "payload": installed,
        "bootstrapper": bootstrapper,
        "icon": icon,
        "license": license_rtf,
    }


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
        machine: ``amd64`` or ``arm64``, as asked for.

    Raises:
        SystemExit: On either mismatch.
    """
    if sys.version_info[:2] != BUILD_PYTHON_VERSION:
        wanted = ".".join(str(part) for part in BUILD_PYTHON_VERSION)
        raise SystemExit(
            f"the client is compiled against Python {wanted}; "
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


def _make_build_environment(venv: Path, machine: str) -> Path:
    """A virtual environment holding the compiler and the window's Python
    side at their pinned versions.

    Args:
        venv: Where to make it.
        machine: ``amd64`` or ``arm64``, which picks the compiled wheel.

    Returns:
        The environment's interpreter.

    Raises:
        SystemExit: When a wheel is not what was pinned, or pip refuses.
    """
    payload.run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "Scripts" / "python.exe"
    payload.run(nuitka_build.pip_install_command(python))
    # Into the environment's own site-packages, which on Windows a venv
    # keeps under Lib; pinned files by path rather than names pip resolves.
    payload.stage_wheels(
        python,
        venv / "Lib" / "site-packages",
        WINDOWS_WHEELS + (WINDOWS_CFFI[machine],),
    )
    return python


def _compile(python: Path, tree: Path, build: Path, version: str) -> Path:
    """Run Nuitka over the staged package, once per subsystem.

    The console program is the standalone directory; the windowed one is
    compiled beside it from the same source and only its executable is
    taken, since everything else the two need is the same.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_client`` package is in.
        build: Where the compiler works.
        version: The version stamped into the binaries' own properties.

    Returns:
        The standalone directory: both binaries and everything beside them.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    console = _compile_one(
        python, tree, build / "console", version, CLIENT_BINARY_NAME, "force"
    )
    windowed = _compile_one(
        python,
        tree,
        build / "windowed",
        version,
        CLIENT_WINDOWED_BINARY_NAME,
        "disable",
    )
    shutil.copyfile(
        windowed / CLIENT_WINDOWED_BINARY_NAME, console / CLIENT_WINDOWED_BINARY_NAME
    )
    return console


def _compile_one(
    python: Path, tree: Path, build: Path, version: str, name: str, console_mode: str
) -> Path:
    """One Nuitka standalone build.

    Args:
        python: The build environment's interpreter.
        tree: The directory the staged ``neutrino_client`` package is in.
        build: Where the compiler works.
        version: The version stamped into the binary's own properties.
        name: What the binary is called.
        console_mode: Nuitka's ``--windows-console-mode`` value.

    Returns:
        The standalone directory: the binary and everything beside it.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    return nuitka_build.compile_standalone(
        python,
        tree / "neutrino_client" / "cli" / "entry.py",
        build,
        name,
        source_root=tree,
        options=(
            "--include-package=neutrino_client",
            "--include-package=webview",
            *(f"--nofollow-import-to={module}" for module in NUITKA_EXCLUDED_BACKENDS),
            *nuitka_build.windows_options(
                product_name="Neutrino Client",
                version=version,
                icon=icons.write_ico(build.parent / "binary.ico"),
                console_mode=console_mode,
            ),
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
    for name in payload.WINDOWS_CARRIED_LICENSES:
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


if __name__ == "__main__":
    raise SystemExit(main())
