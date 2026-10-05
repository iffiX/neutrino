"""Writing a WiX source and building an ``.msi`` from it.

A caller writes the body of its package as WiX XML, with ``@NAME@`` holes
for the values it knows only at build time, and :func:`package_source`
wraps it in the one ``Package`` every installer here shares: per machine,
compressed into itself, upgrading over any earlier version. The element
helpers write the pieces an installer adds to that body, a Windows service
with its control and its permissions, a custom action, a directory, with
every value escaped.

Needs WiX 6: ``dotnet tool install --global wix --version 6.0.2``, and its
Util and UI extensions: ``wix extension add -g WixToolset.Util.wixext/6.0.2``
and the same for ``WixToolset.UI.wixext``. WiX 7 refuses to build until a
maintenance-fee EULA is accepted, and the extension's own 7 does not load in
6.

Not pure: :func:`build` runs wix.
"""

import shutil
import subprocess
import xml.sax.saxutils
from pathlib import Path

# The toolset, and the extensions a source may load at the version this WiX
# loads: Util for CloseApplication, the quiet exec and PermissionEx, UI for
# the wizard's dialogs.
WIX_VERSION = "6.0.2"
WIX_UTIL_EXTENSION = f"WixToolset.Util.wixext/{WIX_VERSION}"
WIX_UI_EXTENSION = f"WixToolset.UI.wixext/{WIX_VERSION}"

# The platform an msi declares for each machine.
MSI_PLATFORMS = {"amd64": "x64", "arm64": "arm64"}

# The library the Util extension keeps its custom actions in, one per
# machine.
UTIL_LIBRARY = {"amd64": "Wix4UtilCA_X64", "arm64": "Wix4UtilCA_A64"}

# The package every installer shares. @NAME@ rather than str.format: the
# body is XML with braces of its own in the property expressions.
PACKAGE_SOURCE = """<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs"
     xmlns:ui="http://wixtoolset.org/schemas/v4/wxs/ui"
     xmlns:util="http://wixtoolset.org/schemas/v4/wxs/util">
  <Package Name="@NAME@"
           Manufacturer="@MANUFACTURER@"
           Version="@VERSION@"
           UpgradeCode="@UPGRADE_CODE@"
           Scope="perMachine"
           Compressed="yes">
    <MajorUpgrade AllowSameVersionUpgrades="yes"@SCHEDULE@
                  DowngradeErrorMessage="A newer @NAME@ is already installed." />
    <MediaTemplate EmbedCab="yes"@COMPRESSION@ />
@BODY@
  </Package>
</Wix>
"""


def attribute_text(value: str) -> str:
    """Text safe inside a double-quoted XML attribute.

    Args:
        value: The plain text.

    Returns:
        The text with markup characters and double quotes escaped.
    """
    return xml.sax.saxutils.escape(value, {'"': "&quot;"})


def fill(template: str, values: dict) -> str:
    """Put each value into its ``@NAME@`` hole, escaped for an attribute.

    Args:
        template: WiX XML with ``@NAME@`` holes.
        values: ``{NAME: text}``.

    Returns:
        The XML with every named hole filled.
    """
    for name, value in values.items():
        template = template.replace(f"@{name}@", attribute_text(str(value)))
    return template


def package_source(
    *,
    name: str,
    manufacturer: str,
    version: str,
    upgrade_code: str,
    body: str,
    compression_level: str = "",
    upgrade_schedule: str = "",
) -> str:
    """The whole ``.wxs`` document around a package's body.

    Args:
        name: The product name.
        manufacturer: The Manufacturer field.
        version: The version being packaged.
        upgrade_code: The product's identity across every version it ships
            as.
        body: The XML inside ``Package``, holes already filled.
        compression_level: The cabinet's ``CompressionLevel``, such as
            ``high``; WiX's own default when empty.
        upgrade_schedule: When the earlier version is removed, as
            ``MajorUpgrade``'s ``Schedule`` names it; WiX's own default when
            empty.

    Returns:
        The .wxs document.
    """
    return (
        fill(
            PACKAGE_SOURCE,
            {
                "NAME": name,
                "MANUFACTURER": manufacturer,
                "VERSION": version,
                "UPGRADE_CODE": upgrade_code,
            },
        )
        .replace(
            "@COMPRESSION@",
            (
                f' CompressionLevel="{attribute_text(compression_level)}"'
                if compression_level
                else ""
            ),
        )
        .replace(
            "@SCHEDULE@",
            (
                f' Schedule="{attribute_text(upgrade_schedule)}"'
                if upgrade_schedule
                else ""
            ),
        )
        .replace("@BODY@", body.rstrip("\n"))
    )


def element(tag: str, attributes: dict, children: tuple = ()) -> str:
    """One XML element with its attributes escaped.

    Args:
        tag: The element's name, with its namespace prefix when it has one.
        attributes: ``{name: value}``, written in order.
        children: Child elements already written.

    Returns:
        The element; self-closing when it has no children.
    """
    written = "".join(
        f' {key}="{attribute_text(str(value))}"' for key, value in attributes.items()
    )
    if not children:
        return f"<{tag}{written} />"
    return f"<{tag}{written}>{''.join(children)}</{tag}>"


def permission_ex(user: str, rights: tuple = ("GenericAll",)) -> str:
    """A ``util:PermissionEx`` granting rights to one account.

    Args:
        user: The account, such as ``Administrators`` or ``LocalSystem``.
        rights: The rights granted, as WiX names them.

    Returns:
        The element.
    """
    return element("util:PermissionEx", {"User": user, **dict.fromkeys(rights, "yes")})


def service_component(
    *,
    component_id: str,
    source: Path,
    service_name: str,
    display_name: str,
    description: str,
    arguments: str = "",
    account: str = "LocalSystem",
    start: str = "auto",
    permissions: tuple = (),
    is_started_on_install: bool = True,
    also: tuple = (),
) -> str:
    """A component holding a service's binary, its registration and its
    control: stopped on install and removal, removed on removal, and
    started on install when asked.

    Args:
        component_id: The component's Id; the file's is derived from it.
        source: The binary on the build machine.
        service_name: The name the service control manager knows.
        display_name: The name the Services console shows.
        description: The description the Services console shows.
        arguments: The command line the service is started with.
        account: The account it runs as.
        start: ``auto``, ``demand`` or ``disabled``.
        permissions: :func:`permission_ex` elements set on the service.
        is_started_on_install: Whether the install starts it; False leaves
            it registered and stopped.
        also: More services the same binary runs, as
            :func:`service_entries` makes them.

    Returns:
        The component element.
    """
    return element(
        "Component",
        {"Id": component_id, "Guid": "*"},
        (
            element(
                "File",
                {"Id": f"{component_id}File", "Source": str(source), "KeyPath": "yes"},
            ),
        )
        + service_entries(
            entry_id=component_id,
            service_name=service_name,
            display_name=display_name,
            description=description,
            arguments=arguments,
            account=account,
            start=start,
            permissions=permissions,
            is_started_on_install=is_started_on_install,
        )
        + tuple(also),
    )


def service_entries(
    *,
    entry_id: str,
    service_name: str,
    display_name: str,
    description: str,
    arguments: str = "",
    account: str = "LocalSystem",
    start: str = "auto",
    permissions: tuple = (),
    is_started_on_install: bool = True,
) -> tuple:
    """One service's registration and control, for the component holding its binary.

    Args:
        entry_id: The prefix of the two elements' Ids.
        service_name: The name the service control manager knows.
        display_name: The name the Services console shows.
        description: The description the Services console shows.
        arguments: The command line the service is started with.
        account: The account it runs as.
        start: ``auto``, ``demand`` or ``disabled``.
        permissions: :func:`permission_ex` elements set on the service.
        is_started_on_install: Whether the install starts it.

    Returns:
        The ``ServiceInstall`` and the ``ServiceControl`` elements.
    """
    install = {
        "Id": f"{entry_id}Install",
        "Name": service_name,
        "DisplayName": display_name,
        "Description": description,
        "Type": "ownProcess",
        "Start": start,
        "ErrorControl": "normal",
        "Account": account,
    }
    if arguments:
        install["Arguments"] = arguments
    control = {"Id": f"{entry_id}Control", "Name": service_name}
    if is_started_on_install:
        control["Start"] = "install"
    control.update({"Stop": "both", "Remove": "uninstall", "Wait": "yes"})
    return (
        element("ServiceInstall", install, permissions),
        element("ServiceControl", control),
    )


def custom_action(
    action_id: str,
    *,
    execute: str = "deferred",
    is_impersonated: bool = False,
    is_failure_ignored: bool = False,
    **attributes: str,
) -> str:
    """A ``CustomAction``.

    Args:
        action_id: Its Id.
        execute: ``immediate`` or ``deferred``.
        is_impersonated: Whether a deferred action runs as the person
            installing rather than as the system.
        is_failure_ignored: Whether its exit code is ignored.
        **attributes: What it runs: ``FileRef`` and ``ExeCommand``,
            ``Directory`` and ``ExeCommand``, or ``BinaryRef`` and
            ``DllEntry``.

    Returns:
        The element.
    """
    written = {"Id": action_id, **attributes, "Execute": execute}
    if execute == "deferred":
        written["Impersonate"] = "yes" if is_impersonated else "no"
    written["Return"] = "ignore" if is_failure_ignored else "check"
    return element("CustomAction", written)


def directory(directory_id: str, name: str, children: tuple = ()) -> str:
    """A ``Directory`` under whatever it is written in.

    Args:
        directory_id: Its Id.
        name: The folder's name on disk.
        children: Directories under it.

    Returns:
        The element.
    """
    return element("Directory", {"Id": directory_id, "Name": name}, children)


def write_license_rtf(source: Path, target: Path) -> Path:
    """Write a plain-text licence as the rich text the wizard's first page
    reads.

    Args:
        source: The licence.
        target: Where to write the RTF.

    Returns:
        The path written.

    Raises:
        SystemExit: When there is no licence at ``source``.
    """
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


def build(
    source: Path,
    target: Path,
    machine: str,
    extensions: tuple = (WIX_UTIL_EXTENSION, WIX_UI_EXTENSION),
) -> None:
    """Run wix over a written source.

    Args:
        source: The .wxs to compile.
        target: Where the .msi should land.
        machine: ``amd64`` or ``arm64``, which the msi declares as its
            platform.
        extensions: The extensions the source's elements come from.

    Raises:
        SystemExit: If WiX is not installed, or refuses the source.
    """
    wix = shutil.which("wix")
    if wix is None:
        added = "".join(f" && wix extension add -g {name}" for name in extensions)
        raise SystemExit(
            "WiX is needed to build a Windows installer: "
            f"dotnet tool install --global wix --version {WIX_VERSION}{added}"
        )
    command = [wix, "build", "-arch", MSI_PLATFORMS[machine]]
    for name in extensions:
        command += ["-ext", name]
    command += ["-out", str(target), str(source)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit((result.stdout or result.stderr).strip())
