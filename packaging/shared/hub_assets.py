"""The programs and databases a hub package carries beside the hub.

xray, cli-proxy-api, netbird, easytier-core and easytier-cli, and on macOS
and Windows tun2socks, each taken out of its own upstream release for one
system and machine and checked against the hash the hub's module states in
its ``<MODULE>_ASSETS`` table, and the v2fly geodata. The Linux packages put
the programs under ``/opt/neutrino/hub/bin``, the macOS and Windows packages
beside ``nhub``; on Windows ``wintun.dll`` comes out of EasyTier's archive
with them, and tun2socks opens its device with that same driver. The
client's Windows package takes its tun2socks from the same pin, which
lives in ``packaging/shared/constants.py`` so the mainland tree holds it too.
A program
or a database whose module the tree does not hold is a feature its edition
leaves out, and is not carried.

Not pure: downloads, writes files.
"""

import hashlib
import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from shared.constants import PACKAGING_TUN2SOCKS_LICENSE

# The hub package, whose modules state every pin read here.
HUB_ROOT = Path(__file__).resolve().parents[2] / "hub"

# Each carried program: the module that pins it, the prefix of its
# constants there, and the files taken out of its archive.
HUB_ASSET_PROGRAMS = {
    "xray": ("neutrino_hub.modules.xray.constants", "XRAY", ("xray",)),
    "cliproxyapi": (
        "neutrino_hub.modules.cliproxyapi.constants",
        "CLIPROXYAPI",
        ("cli-proxy-api",),
    ),
    "netbird": ("neutrino_hub.modules.netbird.constants", "NETBIRD", ("netbird",)),
    "easytier": (
        "neutrino_hub.modules.easytier.constants",
        "EASYTIER",
        ("easytier-core", "easytier-cli"),
    ),
    "tun2socks": ("shared.constants", "PACKAGING_TUN2SOCKS", ("tun2socks",)),
}
# The programs a system's package carries only there; every other program
# goes into every package.
HUB_ASSET_SYSTEMS = {"tun2socks": ("darwin", "windows")}
# The hub module a program pinned outside the hub serves; the hub carries the
# program only where its tree holds that module.
HUB_ASSET_SERVED_MODULES = {"tun2socks": "neutrino_hub.modules.tun.constants"}
# The programs whose archive names the file after the system and machine;
# the module states the name under ``<PREFIX>_ASSET_MEMBER``.
HUB_ASSET_RENAMED = ("tun2socks",)
# What Windows adds beside the programs: the TUN driver EasyTier's archive
# carries.
HUB_ASSET_WINDOWS_EXTRAS = {"easytier": ("wintun.dll",)}
HUB_ASSET_WINDOWS_SUFFIX = ".exe"
# The module that pins the geodata.
HUB_ASSET_GEODATA_MODULE = "neutrino_hub.modules.xray.constants"
# The licence under licenses/ of each carried program, of what Windows adds
# beside them, and of the geodata.
HUB_ASSET_LICENSES = {
    "xray": "xray_core.txt",
    "cliproxyapi": "cliproxyapi.txt",
    "netbird": "netbird.txt",
    "easytier": "easytier.txt",
    "tun2socks": PACKAGING_TUN2SOCKS_LICENSE,
}
HUB_ASSET_WINDOWS_EXTRA_LICENSES = {"wintun.dll": "wintun.txt"}
HUB_ASSET_GEODATA_LICENSES = ("v2fly_geoip.txt", "v2fly_domain_list_community.txt")
HUB_ASSET_FETCH_TIMEOUT_S = 300


def pinned(program: str, os_name: str, machine: str) -> tuple:
    """Where one program's pinned release asset is, and its hash.

    Args:
        program: A key of :data:`HUB_ASSET_PROGRAMS`.
        os_name: ``linux``, ``darwin`` or ``windows``.
        machine: ``amd64`` or ``arm64``.

    Returns:
        ``(url, sha256)``.

    Raises:
        SystemExit: When nothing is pinned for that system and machine.
    """
    module, prefix, _names = HUB_ASSET_PROGRAMS[program]
    version, url, assets = _runtime(
        module, f"{prefix}_VERSION", f"{prefix}_RELEASE_URL", f"{prefix}_ASSETS"
    )
    if (os_name, machine) not in assets:
        published = ", ".join(f"{system} {arch}" for system, arch in sorted(assets))
        raise SystemExit(
            f"no {program} pinned for {os_name} {machine}; there is one for: "
            f"{published}"
        )
    asset, digest = assets[(os_name, machine)]
    return url.format(version=version, asset=asset), digest


def carried_names(os_name: str) -> list:
    """The files :func:`stage_programs` writes for one system.

    Args:
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        File names, in the order they are staged.
    """
    names = []
    for program, (_module, _prefix, files) in HUB_ASSET_PROGRAMS.items():
        if not _is_carried(program, os_name):
            continue
        names += [_on(os_name, name) for name in files]
        if os_name == "windows":
            names += list(HUB_ASSET_WINDOWS_EXTRAS.get(program, ()))
    return names


def carried_licenses(os_name: str) -> list:
    """The licences of what :func:`stage_programs` and :func:`stage_geodata`
    put into one system's package.

    Args:
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        File names under ``licenses/``.
    """
    names = []
    for program in HUB_ASSET_PROGRAMS:
        if not _is_carried(program, os_name):
            continue
        names.append(HUB_ASSET_LICENSES[program])
        if os_name == "windows":
            names += [
                HUB_ASSET_WINDOWS_EXTRA_LICENSES[extra]
                for extra in HUB_ASSET_WINDOWS_EXTRAS.get(program, ())
            ]
    if _has_module(HUB_ASSET_GEODATA_MODULE):
        names += list(HUB_ASSET_GEODATA_LICENSES)
    return names


def stage_programs(binaries: Path, os_name: str, machine: str) -> list:
    """Put every carried program for one system and machine into a directory.

    Args:
        binaries: The directory they belong in.
        os_name: ``linux``, ``darwin`` or ``windows``.
        machine: ``amd64`` or ``arm64``.

    Returns:
        The files written.

    Raises:
        SystemExit: When a program is not pinned for the system and machine,
            what arrived is not what was pinned, or an archive lacks a file.
    """
    binaries.mkdir(parents=True, exist_ok=True)
    written = []
    for program in HUB_ASSET_PROGRAMS:
        if _is_carried(program, os_name):
            written += stage_program(binaries, program, os_name, machine)
    return written


def stage_program(binaries: Path, program: str, os_name: str, machine: str) -> list:
    """Put one pinned program for one system and machine into a directory.

    Args:
        binaries: The directory it belongs in.
        program: A key of :data:`HUB_ASSET_PROGRAMS`.
        os_name: ``linux``, ``darwin`` or ``windows``.
        machine: ``amd64`` or ``arm64``.

    Returns:
        The files written.

    Raises:
        SystemExit: When the program is not pinned for the system and
            machine, what arrived is not what was pinned, or its archive
            lacks a file.
    """
    module, prefix, files = HUB_ASSET_PROGRAMS[program]
    binaries.mkdir(parents=True, exist_ok=True)
    url, digest = pinned(program, os_name, machine)
    payload = fetch(url, digest, program)
    wanted = [_on(os_name, name) for name in files]
    if os_name == "windows":
        wanted += list(HUB_ASSET_WINDOWS_EXTRAS.get(program, ()))
    names = dict(zip(wanted, wanted))
    if program in HUB_ASSET_RENAMED:
        member = _runtime(module, f"{prefix}_ASSET_MEMBER")
        (staged,) = [_on(os_name, name) for name in files]
        names = {_on(os_name, member.format(os_name=os_name, machine=machine)): staged}
    written = []
    for name, content in _members(payload, url, list(names)).items():
        target = binaries / names[name]
        target.write_bytes(content)
        target.chmod(0o755)
        written.append(target)
    return written


def pinned_version(program: str) -> str:
    """The release of one program the packages carry.

    Args:
        program: A key of :data:`HUB_ASSET_PROGRAMS`.

    Returns:
        The version, as its module pins it.
    """
    module, prefix, _files = HUB_ASSET_PROGRAMS[program]
    return _runtime(module, f"{prefix}_VERSION")


def stage_geodata(geodata: Path) -> list:
    """Put the pinned v2fly databases into a directory.

    Args:
        geodata: The directory they belong in.

    Returns:
        The files written.

    Raises:
        SystemExit: When what arrived is not what was pinned.
    """
    if not _has_module(HUB_ASSET_GEODATA_MODULE):
        return []
    geodata.mkdir(parents=True, exist_ok=True)
    written = []
    pins = _runtime(HUB_ASSET_GEODATA_MODULE, "XRAY_GEODATA")
    for file_name, pin in pins.items():
        target = geodata / file_name
        target.write_bytes(fetch(pin["url"], pin["sha256"], file_name))
        target.chmod(0o644)
        written.append(target)
    return written


def fetch(url: str, digest: str, what: str) -> bytes:
    """Download one pinned file and check it against its hash.

    Args:
        url: Where it lives.
        digest: The pinned SHA-256.
        what: The component, for the messages.

    Returns:
        The file's bytes.

    Raises:
        SystemExit: When what arrived is not what was pinned.
    """
    print(f"  fetching {what} {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=HUB_ASSET_FETCH_TIMEOUT_S) as response:
        payload = response.read()
    arrived = hashlib.sha256(payload).hexdigest()
    if arrived != digest:
        raise SystemExit(
            f"{what} at {url} hashes to {arrived}, not the pinned {digest}"
        )
    return payload


def _is_carried(program: str, os_name: str) -> bool:
    """Whether a system's package carries one program."""
    served = HUB_ASSET_SERVED_MODULES.get(program, HUB_ASSET_PROGRAMS[program][0])
    if not _has_module(served):
        return False
    return os_name in HUB_ASSET_SYSTEMS.get(program, (os_name,))


def stamped_versions() -> dict:
    """The versions the hub reads from its stamp: of each carried program
    pinned outside the hub, where the tree holds the module it serves.

    Returns:
        The version of each such program, by name.
    """
    return {
        program: pinned_version(program)
        for program, served in HUB_ASSET_SERVED_MODULES.items()
        if _has_module(served)
    }


def _has_module(module_name: str) -> bool:
    """Whether the tree holds one of the hub's modules."""
    return (HUB_ROOT / (module_name.replace(".", "/") + ".py")).is_file()


def _on(os_name: str, name: str) -> str:
    """A program's file name on one system."""
    return name + HUB_ASSET_WINDOWS_SUFFIX if os_name == "windows" else name


def _members(payload: bytes, url: str, wanted: list) -> dict:
    """The named files out of a zip or a gzipped tarball, wherever they sit.

    Args:
        payload: The archive's bytes.
        url: Where it came from, whose name says its format.
        wanted: The file names to take, matched on the last path part.

    Returns:
        File name to contents.

    Raises:
        SystemExit: When the archive lacks one of them.
    """
    found = {}
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            for member in bundle.namelist():
                name = member.rsplit("/", 1)[-1]
                if name in wanted and name not in found:
                    found[name] = bundle.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
            for member in bundle.getmembers():
                name = member.name.rsplit("/", 1)[-1]
                if member.isfile() and name in wanted and name not in found:
                    found[name] = bundle.extractfile(member).read()
    missing = [name for name in wanted if name not in found]
    if missing:
        raise SystemExit(f"{url} carries no {', '.join(missing)}")
    return {name: found[name] for name in wanted}


def _runtime(module_name: str, *names):
    """Constants the hub's own modules state, read from the checkout.

    Args:
        module_name: The module to read.
        *names: The constants to take from it.

    Returns:
        One value, or a tuple of them when more than one was asked for.
    """
    if str(HUB_ROOT) not in sys.path:
        sys.path.insert(0, str(HUB_ROOT))
    module = __import__(module_name, fromlist=list(names))
    values = tuple(getattr(module, name) for name in names)
    return values[0] if len(values) == 1 else values
