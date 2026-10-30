"""The one-command installer for macOS and Linux, run against stand-ins.

``install.sh`` runs under ``sh`` with ``uname``, ``id``, ``sudo`` and every
package manager replaced by scripts that record what they were asked, and
the real ``curl`` against stand-in release sites on 127.0.0.1, so what is
asserted is the package each system and machine takes, the command that
installs it, the site and the release it comes from, the move to the next
site on a stall, an error or other bytes, the checksum that stops a wrong
file, the one sentence each refusal prints, and the wait while another
program holds dpkg's or dnf's lock, its holder named whole from a stand-in
of the kernel's process list. The fake ``nhub`` lies outside the path,
where the script must name it whole.
"""

import hashlib
import json
import sys
import os
import re
import subprocess
import threading
from pathlib import Path

import pytest

from shared import install_script_stamp
from shared.constants import PACKAGING_RELEASE_SITES

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "install" / "install.sh"
RELATIVE = "packaging/install/install.sh"
TAG = "v9.9.9"
# The edition of the tree the suite runs in. The mainland tree is written
# from the intl checkout, whose scripts hold the committed lines a build
# stamps, and from nothing else.
TREE_EDITION = (SCRIPT.parents[2] / "EDITION").read_text().strip()
from_intl_tree = pytest.mark.skipif(
    TREE_EDITION != "intl",
    reason="the mainland tree is written from the intl checkout",
)

PACKAGES = (
    "neutrino-hub_9.9.9_amd64.deb",
    "neutrino-hub_9.9.9_arm64.deb",
    "neutrino-agent_9.9.9_amd64.deb",
    "neutrino-hub-9.9.9-1.x86_64.rpm",
    "neutrino-hub-9.9.9-1.aarch64.rpm",
    "neutrino-agent-9.9.9-1.x86_64.rpm",
    "neutrino-client-9.9.9-1.x86_64.rpm",
    "neutrino-hub-9.9.9-1-x86_64.pkg.tar.zst",
    "neutrino-hub-9.9.9-macos-arm64.pkg",
    "neutrino-hub-9.9.9-macos-amd64.pkg",
    "neutrino-client-9.9.9-macos-amd64.pkg",
    "neutrino-hub-9.9.9-windows-amd64.msi",
    "neutrino-hub_9.9.9_amd64-cn.deb",
    "neutrino-hub_9.9.9_arm64-cn.deb",
    "neutrino-hub-9.9.9-1.x86_64-cn.rpm",
    "neutrino-hub-9.9.9-1-x86_64-cn.pkg.tar.zst",
    "neutrino-hub-9.9.9-macos-amd64-cn.pkg",
    "install.sh",
    "install-cn.sh",
)

OS_RELEASES = {
    "ubuntu": 'ID=ubuntu\nID_LIKE="debian"\nVERSION_ID="24.04"\n',
    "fedora": 'ID=fedora\nVERSION_ID="41"\n',
    "rocky": 'ID="rocky"\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.4"\n',
    "almalinux": 'ID="almalinux"\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.5"\n',
    "rhel": 'ID="rhel"\nID_LIKE="fedora"\nVERSION_ID="9.4"\n',
    "arch": "ID=arch\n",
    "suse": 'ID="opensuse-leap"\nID_LIKE="suse opensuse"\n',
}

RECORDER = """#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_LOG"
"""

FAKES = {
    "uname": """#!/bin/sh
case "$1" in -s) echo "$FAKE_SYSTEM" ;; -m) echo "$FAKE_MACHINE" ;; esac
""",
    "id": """#!/bin/sh
echo "$FAKE_UID"
""",
    "sudo": """#!/bin/sh
echo "sudo $*" >> "$FAKE_LOG"
case "$1" in
    -v) [ -z "$FAKE_SUDO_REFUSED" ] || exit 1; : > "$FAKE_TICKET"; exit 0 ;;
    -n)
        shift
        [ -n "$FAKE_SUDO_FREE" ] || [ -f "$FAKE_TICKET" ] || exit 1
        ;;
esac
exec "$@"
""",
    "getent": """#!/bin/sh
[ "$1" = passwd ] && [ "$2" = "$FAKE_SUDO_USER_NAME" ] || exit 2
echo "$2:x:1001:1001::$FAKE_SUDO_USER_HOME:/bin/sh"
""",
    "installer": RECORDER,
    "apt-get": RECORDER,
    "dnf": """#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_LOG"
if [ -n "${FAKE_DNF_LOCKED:-}" ] && [ -s "$FAKE_DNF_LOCKED" ]; then
    sed -i 1d "$FAKE_DNF_LOCKED"
    echo "Failed to obtain rpm transaction lock. Another transaction is in progress."
    exit 1
fi
case "$*" in *"${FAKE_DNF_REFUSED:-no refusal}"*) exit 1 ;; esac
""",
    "subscription-manager": RECORDER,
    "pacman": RECORDER,
}

NHUB = """#!/bin/sh
echo "nhub $*" >> "$FAKE_LOG"
if [ -n "$FAKE_ADDRESS" ]; then echo "$FAKE_ADDRESS"; fi
"""

# What a set-up hub's panel settings hold, and what a fresh one's do.
SET_UP_SETTINGS = (
    '{\n  "admin_password_hash": "scrypt$73616c74$6b6579"\n}\n'  # scan: allow
)
FRESH_SETTINGS = (
    '{\n  "admin_password_hash": "PLACEHOLDER_ARGON2ID_HASH"\n}\n'  # scan: allow
)


def _write_sums(served):
    """SHA256SUMS over every file the release holds."""
    lines = []
    for path in sorted(served.iterdir()):
        if path.name in ("SHA256SUMS", "latest.json"):
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (served / "SHA256SUMS").write_text("\n".join(lines) + "\n")


@pytest.fixture
def stand_ins(tmp_path, release_sites):
    """The fakes on the path, two release sites serving one release of fake
    packages, and how to run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in FAKES.items():
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "nhub").write_text(NHUB)
    (programs / "nhub").chmod(0o755)
    served = release_sites.served
    for name in PACKAGES:
        (served / name).write_bytes(name.encode())
    _write_sums(served)
    (served / "latest.json").write_text(json.dumps({"tag": TAG, "version": "9.9.9"}))
    first = release_sites()
    second = release_sites()
    log = tmp_path / "log"

    def run(
        *arguments,
        system="Linux",
        machine="x86_64",
        os_release="ubuntu",
        uid="1000",
        environment=None,
        edition="intl",
        sites=None,
        script=SCRIPT,
        lock_wait_s=300,
    ):
        release_file = tmp_path / "os-release"
        release_file.write_text(OS_RELEASES[os_release])
        functions = tmp_path / "functions.sh"
        text = re.sub(
            r'^EDITION="[a-z]+"$',
            f'EDITION="{edition}"' if edition else r"\g<0>",
            script.read_text(),
            count=1,
            flags=re.MULTILINE,
        )
        assert text.rstrip().endswith('main "$@"')
        functions.write_text(text.rstrip()[: -len('main "$@"')])
        addresses = " ".join(
            f"{site.files} {site.latest}" if hasattr(site, "files") else " ".join(site)
            for site in ((first, second) if sites is None else sites)
        )
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FAKE_LOG": str(log),
            "FAKE_SYSTEM": system,
            "FAKE_MACHINE": machine,
            "FAKE_UID": uid,
            "FAKE_TICKET": str(tmp_path / "ticket"),
            "HOME": str(tmp_path),
            **(environment or {}),
        }
        result = subprocess.run(
            [
                "sh",
                "-c",
                f'. "{functions}"; RELEASE_SITES="{addresses}"; '
                "PROBE_WAIT_S=1; STALL_S=1; "
                f'OS_RELEASE="{release_file}"; '
                f'AGENT_BINDING_LINUX="{tmp_path}/agent.json"; '
                f'AGENT_BINDING_MACOS="{tmp_path}/agent.json"; '
                f'HUB_COMMAND_LINUX="{programs}/nhub"; '
                f'HUB_COMMAND_MACOS="{programs}/nhub"; '
                f'HUB_SETTINGS_LINUX="{tmp_path}/settings.json"; '
                f'HUB_SETTINGS_MACOS="{tmp_path}/settings.json"; '
                f'APT_LOCKS="{run.dpkg_lock} {run.lists_lock}"; '
                f'DNF_LOCK_FILES="{run.dnf_lock}"; '
                f'PROC_LOCKS="{run.locks}"; PROC_DIR="{run.proc}"; '
                f'LOCK_WAIT_S={lock_wait_s}; main "$@"',
                "install.sh",
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            timeout=60,
        )
        asked = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        (tmp_path / "ticket").unlink(missing_ok=True)
        return result, asked

    run.served = served
    run.first = first
    run.second = second
    run.dpkg_lock = tmp_path / "lock-frontend"
    run.dpkg_lock.write_text("")
    run.lists_lock = tmp_path / "lists-lock"
    run.lists_lock.write_text("")
    run.dnf_lock = tmp_path / "rpmdb_lock.pid"
    run.locks = tmp_path / "locks"
    run.locks.write_text("")
    run.proc = tmp_path / "proc"
    run.dead = release_sites.dead
    run.dead_host = release_sites.dead_host
    run.open_site = release_sites
    run.nhub = programs / "nhub"
    run.settings = tmp_path / "settings.json"
    return run


def _installs(asked):
    return [line for line in asked if not line.startswith(("sudo", "nhub"))]


def _said(result):
    """The one sentence a refusal ends on."""
    return result.stderr.strip().splitlines()[-1]


def _publish(served, name, data):
    """One more file in the release, with SHA256SUMS written again."""
    (served / name).write_bytes(data)
    _write_sums(served)


def test_the_script_is_posix_sh_and_ends_by_running_main():
    result = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert SCRIPT.read_text().startswith("#!/bin/sh\n")
    assert os.access(SCRIPT, os.X_OK)


def test_a_debian_machine_installs_the_hub_deb_from_the_latest_release(stand_ins):
    result, asked = stand_ins()

    assert result.returncode == 0, result.stderr
    (install,) = _installs(asked)
    assert install.startswith("apt-get install -y -o DPkg::Lock::Timeout=300 /")
    assert install.endswith("/neutrino-hub_9.9.9_amd64.deb")
    assert any(line.startswith("sudo apt-get install -y") for line in asked)
    paths = [
        path
        for site in (stand_ins.first, stand_ins.second)
        for path, _ in site.requests
    ]
    assert "/latest.json" in paths
    assert f"/download/{TAG}/SHA256SUMS" in paths
    assert f"/download/{TAG}/neutrino-hub_9.9.9_amd64.deb" in paths


def test_a_pinned_version_comes_from_that_release_and_reads_no_latest(stand_ins):
    result, _asked = stand_ins(environment={"NEUTRINO_VERSION": "v9.9.8"})

    assert result.returncode == 0, result.stderr
    paths = [
        path
        for site in (stand_ins.first, stand_ins.second)
        for path, _ in site.requests
    ]
    assert "/latest.json" not in paths
    assert "/download/v9.9.8/neutrino-hub_9.9.9_amd64.deb" in paths
    assert not any(path.startswith(f"/download/{TAG}/") for path in paths)


def test_the_component_names_the_package(stand_ins):
    result, asked = stand_ins("agent")

    assert result.returncode == 0, result.stderr
    (install,) = _installs(asked)
    assert install.endswith("/neutrino-agent_9.9.9_amd64.deb")


@pytest.mark.parametrize(
    "os_release, machine, command, name",
    [
        ("fedora", "aarch64", "dnf install -y", "neutrino-hub-9.9.9-1.aarch64.rpm"),
        ("rocky", "x86_64", "dnf install -y", "neutrino-hub-9.9.9-1.x86_64.rpm"),
        (
            "ubuntu",
            "aarch64",
            "apt-get install -y -o DPkg::Lock::Timeout=300",
            "neutrino-hub_9.9.9_arm64.deb",
        ),
        (
            "arch",
            "x86_64",
            "pacman -U --noconfirm",
            "neutrino-hub-9.9.9-1-x86_64.pkg.tar.zst",
        ),
    ],
)
def test_each_linux_family_installs_its_own_package(
    stand_ins, os_release, machine, command, name
):
    result, asked = stand_ins(os_release=os_release, machine=machine)

    assert result.returncode == 0, result.stderr
    install = _installs(asked)[-1]
    assert install.startswith(command + " /")
    assert install.endswith("/" + name)


# EPEL's own steps on each RHEL-family system, CRB first.
EPEL_STEPS = {
    "rocky": ["dnf config-manager --set-enabled crb", "dnf install -y epel-release"],
    "almalinux": [
        "dnf config-manager --set-enabled crb",
        "dnf install -y epel-release",
    ],
    "rhel": [
        "subscription-manager repos --enable codeready-builder-for-rhel-9-x86_64-rpms",
        "dnf install -y "
        "https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm",
    ],
}


@pytest.mark.parametrize("component", ["hub", "agent", "client"])
@pytest.mark.parametrize("os_release", ["rocky", "almalinux", "rhel"])
def test_the_rhel_family_enables_epel_before_the_package_under_the_one_sudo(
    stand_ins, os_release, component
):
    """xdotool of the agent and the client, and fail2ban and arp-scan of the
    hub, come from EPEL there."""
    result, asked = stand_ins(component, os_release=os_release)

    assert result.returncode == 0, result.stderr
    installs = _installs(asked)
    assert installs[:2] == EPEL_STEPS[os_release]
    assert installs[2].startswith("dnf install -y /")
    assert installs[2].endswith(f"/neutrino-{component}-9.9.9-1.x86_64.rpm")
    assert len(installs) == 3
    for step in EPEL_STEPS[os_release]:
        assert f"sudo {step}" in asked
    assert asked.count("sudo -v") == 1


def test_rhel_on_arm64_enables_the_code_ready_builder_of_its_machine(stand_ins):
    result, asked = stand_ins(os_release="rhel", machine="aarch64")

    assert result.returncode == 0, result.stderr
    assert _installs(asked)[0] == (
        "subscription-manager repos --enable codeready-builder-for-rhel-9-aarch64-rpms"
    )
    assert _installs(asked)[-1].endswith("/neutrino-hub-9.9.9-1.aarch64.rpm")


def test_root_enables_epel_without_sudo(stand_ins):
    result, asked = stand_ins(os_release="rocky", uid="0")

    assert result.returncode == 0, result.stderr
    assert _installs(asked)[:2] == EPEL_STEPS["rocky"]
    assert not any(line.startswith("sudo") for line in asked)


@pytest.mark.parametrize("refused", ["crb", "epel-release"])
def test_a_refused_epel_step_installs_nothing(stand_ins, refused):
    result, asked = stand_ins(
        os_release="rocky", environment={"FAKE_DNF_REFUSED": refused}
    )

    assert result.returncode == 1
    assert _said(result) == "EPEL could not be enabled; nothing was installed."
    assert not any(line.startswith("dnf install -y /") for line in asked)


@pytest.mark.parametrize(
    "os_release, machine",
    [("fedora", "x86_64"), ("ubuntu", "x86_64"), ("arch", "x86_64")],
)
def test_no_other_system_takes_an_epel_step(stand_ins, os_release, machine):
    result, asked = stand_ins(os_release=os_release, machine=machine)

    assert result.returncode == 0, result.stderr
    assert len(_installs(asked)) == 1
    assert not any(
        word in line
        for line in asked
        for word in ("epel", "crb", "subscription-manager")
    )


@pytest.mark.parametrize(
    "machine, name",
    [
        ("arm64", "neutrino-hub-9.9.9-macos-arm64.pkg"),
        ("x86_64", "neutrino-hub-9.9.9-macos-amd64.pkg"),
    ],
)
def test_a_mac_installs_the_pkg_of_its_machine(stand_ins, machine, name):
    result, asked = stand_ins(system="Darwin", machine=machine)

    assert result.returncode == 0, result.stderr
    (install,) = _installs(asked)
    assert install.startswith("installer -pkg /")
    assert install.endswith(f"/{name} -target /")


def test_without_a_terminal_the_hub_prints_the_wizard_address(stand_ins):
    address = "http://192.0.2.1:8080/?token=t0ken"
    result, asked = stand_ins(
        system="Darwin", machine="arm64", environment={"FAKE_ADDRESS": address}
    )

    assert result.stdout.strip().splitlines()[-1] == (
        f"Next, set the hub up in a browser at: {address}"
    )
    assert f"sudo -n {stand_ins.nhub} open --print" in asked
    assert not any(line.startswith("nhub setup") for line in asked)


def test_without_an_address_the_hub_says_how_to_open_the_wizard(stand_ins):
    result, _asked = stand_ins(system="Darwin", machine="arm64")

    assert result.stdout.strip().splitlines()[-1] == (
        "Next, set the hub up: sudo nhub open"
    )


def test_an_agent_prints_no_wizard_address(stand_ins):
    result, asked = stand_ins("agent")

    assert "Set the hub up" not in result.stdout
    assert not any(line.startswith("nhub") for line in asked)


def test_root_installs_without_sudo(stand_ins):
    result, asked = stand_ins(uid="0")

    assert result.returncode == 0, result.stderr
    assert not any(line.startswith("sudo") for line in asked)


def test_local_files_install_with_nothing_downloaded(stand_ins):
    result, asked = stand_ins(
        "client",
        system="Darwin",
        machine="x86_64",
        environment={"NEUTRINO_ASSET_DIR": str(stand_ins.served)},
    )

    assert result.returncode == 0, result.stderr
    assert stand_ins.first.requests == [] and stand_ins.second.requests == []
    (install,) = _installs(asked)
    assert f"{stand_ins.served}/neutrino-client-9.9.9-macos-amd64.pkg" in install


def test_local_files_need_no_release_site(stand_ins):
    result, _asked = stand_ins(
        "client",
        system="Darwin",
        machine="x86_64",
        sites=(),
        environment={"NEUTRINO_ASSET_DIR": str(stand_ins.served)},
    )

    assert result.returncode == 0, result.stderr


def test_a_download_names_its_site_its_checksum_and_the_install(stand_ins):
    result, _asked = stand_ins()

    lines = result.stdout.splitlines()
    name = "neutrino-hub_9.9.9_amd64.deb"
    assert re.fullmatch(r"Downloaded SHA256SUMS from 127\.0\.0\.1:\d+", lines[0])
    assert re.fullmatch(
        rf"Downloaded {re.escape(name)} from 127\.0\.0\.1:\d+", lines[1]
    )
    assert lines[2:5] == [
        f"{name} matches its SHA256SUMS line",
        f"Installing {name}",
        f"Installed {name}",
    ]


def test_local_files_name_the_directory_they_came_from(stand_ins):
    result, _asked = stand_ins(
        "client",
        system="Darwin",
        machine="x86_64",
        environment={"NEUTRINO_ASSET_DIR": str(stand_ins.served)},
    )

    name = "neutrino-client-9.9.9-macos-amd64.pkg"
    assert result.stdout.splitlines()[:4] == [
        f"Found {name} in {stand_ins.served}",
        f"{name} matches its SHA256SUMS line",
        f"Installing {name}",
        f"Installed {name}",
    ]


def test_a_local_package_that_does_not_match_its_checksum_is_never_installed(
    stand_ins,
):
    (stand_ins.served / "neutrino-hub_9.9.9_amd64.deb").write_bytes(b"tampered")

    result, asked = stand_ins(environment={"NEUTRINO_ASSET_DIR": str(stand_ins.served)})

    assert result.returncode == 1
    assert _said(result) == (
        "neutrino-hub_9.9.9_amd64.deb does not match its SHA256SUMS line; "
        "nothing was installed."
    )
    assert _installs(asked) == []


@pytest.mark.parametrize(
    "arguments, options, said",
    [
        (
            (),
            {"machine": "armv7l"},
            "No Neutrino package is published for armv7l.",
        ),
        (
            (),
            {"os_release": "suse"},
            "No Neutrino package is published for this Linux distribution.",
        ),
        (
            (),
            {"os_release": "arch", "machine": "aarch64"},
            "No Neutrino hub package is published for arch on arm64.",
        ),
        (
            ("agent",),
            {"system": "Darwin", "machine": "arm64"},
            "The release publishes no Neutrino agent package for macos on arm64.",
        ),
        (
            ("router",),
            {},
            "Name hub, agent or client to install, not router.",
        ),
        (
            (),
            {"system": "FreeBSD"},
            "No Neutrino package is published for FreeBSD.",
        ),
    ],
)
def test_a_system_with_no_package_stops_with_one_sentence(
    stand_ins, arguments, options, said
):
    result, asked = stand_ins(*arguments, **options)

    assert result.returncode == 1
    assert _said(result) == said
    assert _installs(asked) == []


# --- the release sites ---


def test_a_checkout_names_no_site_and_stops_with_one_sentence(stand_ins):
    result, asked = stand_ins(sites=())

    assert result.returncode == 1
    assert _said(result) == (
        "This script names no release site; take it from a release, or set "
        "NEUTRINO_ASSET_DIR."
    )
    assert asked == []


def test_the_tree_s_script_names_the_sites_of_its_edition():
    """The GitHub checkout's script names none; the mainland tree's, which
    CNB serves, names every release site."""
    sites = (
        install_script_stamp.sites_text(RELATIVE, PACKAGING_RELEASE_SITES)
        if TREE_EDITION == "cn"
        else ""
    )

    assert f'\nRELEASE_SITES="{sites}"\n' in SCRIPT.read_text()


def test_the_fastest_site_serves_the_package(stand_ins):
    name = "neutrino-hub_9.9.9_amd64.deb"
    _publish(stand_ins.served, name, os.urandom(1536 * 1024))
    stand_ins.first.chunk_delay_s = 0.05

    result, _asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert stand_ins.first.downloads(name) == []
    assert stand_ins.second.downloads(name) == [""]
    assert f"Downloaded {name} from {stand_ins.second.host}" in result.stdout


def test_a_stalled_download_resumes_on_the_next_site_where_it_stopped(stand_ins):
    name = "neutrino-hub_9.9.9_amd64.deb"
    data = os.urandom(3 * 1024 * 1024)
    _publish(stand_ins.served, name, data)
    stand_ins.first.stall_at = 2 * 1024 * 1024
    stand_ins.second.chunk_delay_s = 0.05

    result, asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert stand_ins.first.downloads(name) == [""]
    (resumed,) = stand_ins.second.downloads(name)
    offset = int(re.fullmatch(r"bytes=(\d+)-", resumed).group(1))
    assert offset >= 2 * 1024 * 1024
    assert f"Downloaded {name} from {stand_ins.second.host}" in result.stdout
    (install,) = _installs(asked)
    assert install.endswith("/" + name)


def test_a_site_serving_other_bytes_is_dropped_and_the_next_serves(stand_ins):
    name = "neutrino-hub_9.9.9_amd64.deb"
    _publish(stand_ins.served, name, os.urandom(1536 * 1024))
    stand_ins.first.is_wrong = True
    stand_ins.second.chunk_delay_s = 0.05

    result, asked = stand_ins(environment={"NEUTRINO_VERSION": TAG})

    assert result.returncode == 0, result.stderr
    assert stand_ins.first.downloads(name) == [""]
    assert stand_ins.second.downloads(name) == [""]
    assert f"Downloaded {name} from {stand_ins.second.host}" in result.stdout
    assert len(_installs(asked)) == 1


def test_a_site_missing_the_files_is_one_failed_source(stand_ins):
    stand_ins.first.is_missing = True

    result, asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert len(_installs(asked)) == 1


def test_a_site_nothing_listens_on_is_one_failed_source(stand_ins):
    result, asked = stand_ins(sites=(stand_ins.dead, stand_ins.second))

    assert result.returncode == 0, result.stderr
    assert len(_installs(asked)) == 1


def test_a_site_that_does_not_answer_in_time_is_tried_after_the_others(stand_ins):
    stand_ins.first.is_hanging = True
    name = "neutrino-hub_9.9.9_amd64.deb"

    result, _asked = stand_ins(environment={"NEUTRINO_VERSION": TAG})

    assert result.returncode == 0, result.stderr
    assert f"Downloaded {name} from {stand_ins.second.host}" in result.stdout


def test_a_site_that_answers_a_range_with_the_whole_file_is_never_moved_to(
    stand_ins,
):
    name = "neutrino-hub_9.9.9_amd64.deb"
    _publish(stand_ins.served, name, os.urandom(3 * 1024 * 1024))
    stand_ins.first.stall_at = 2 * 1024 * 1024
    stand_ins.second.is_rangeless = True
    stand_ins.second.chunk_delay_s = 0.05

    result, asked = stand_ins(environment={"NEUTRINO_VERSION": TAG})

    assert result.returncode == 1
    assert _said(result) == (
        f"No release site served {name}: {stand_ins.first.host} (stalled), "
        f"{stand_ins.second.host} (http_200)."
    )
    assert _installs(asked) == []


def test_no_site_serving_the_package_stops_naming_each_site_and_why(stand_ins):
    name = "neutrino-hub_9.9.9_amd64.deb"
    (stand_ins.served / name).unlink()

    result, asked = stand_ins(sites=(stand_ins.first, stand_ins.dead))

    assert result.returncode == 1
    assert _said(result) == (
        f"No release site served {name}: {stand_ins.first.host} (http_404), "
        f"{stand_ins.dead_host} (unreachable)."
    )
    assert _installs(asked) == []


def test_every_site_serving_other_bytes_installs_nothing(stand_ins):
    stand_ins.first.is_wrong = True
    stand_ins.second.is_wrong = True
    name = "neutrino-hub_9.9.9_amd64.deb"

    result, asked = stand_ins(environment={"NEUTRINO_VERSION": TAG})

    assert result.returncode == 1
    hosts = sorted([stand_ins.first.host, stand_ins.second.host])
    said = _said(result)
    assert said.startswith(f"No release site served {name}: ")
    assert sorted(re.findall(r"(127\.0\.0\.1:\d+) \(digest_mismatch\)", said)) == hosts
    assert _installs(asked) == []


@pytest.mark.parametrize("fast_tag", ["v9.9.9", "v9.9.8"])
def test_the_latest_release_is_the_fastest_answer_that_names_a_tag(stand_ins, fast_tag):
    slow_tag = "v9.9.8" if fast_tag == "v9.9.9" else "v9.9.9"
    stand_ins.first.latest_text = json.dumps({"tag": slow_tag})
    stand_ins.first.latest_delay_s = 0.5
    stand_ins.second.latest_text = json.dumps({"tag": fast_tag})

    result, _asked = stand_ins()

    assert result.returncode == 0, result.stderr
    paths = [
        path
        for site in (stand_ins.first, stand_ins.second)
        for path, _ in site.requests
    ]
    assert f"/download/{fast_tag}/SHA256SUMS" in paths
    assert not any(path.startswith(f"/download/{slow_tag}/") for path in paths)


def test_a_site_that_does_not_answer_leaves_the_tag_to_the_others(stand_ins):
    stand_ins.first.is_hanging = True

    result, _asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert (f"/download/{TAG}/SHA256SUMS", "") in stand_ins.second.requests


def test_no_site_naming_the_latest_release_stops_naming_each_site(stand_ins):
    (stand_ins.served / "latest.json").write_text('{"version": "9.9.9"}')

    result, asked = stand_ins(sites=(stand_ins.first, stand_ins.dead))

    assert result.returncode == 1
    assert _said(result) == (
        "No release site named the latest release: "
        f"{stand_ins.first.host} (no_tag), {stand_ins.dead_host} (unreachable)."
    )
    assert _installs(asked) == []


# --- the edition ---


def test_the_script_names_the_edition_of_its_tree():
    edition = (SCRIPT.parents[2] / "EDITION").read_text().strip()

    assert f'\nEDITION="{edition}"\n' in SCRIPT.read_text()


@pytest.mark.parametrize(
    "os_release, system, machine, name",
    [
        ("ubuntu", "Linux", "x86_64", "neutrino-hub_9.9.9_amd64-cn.deb"),
        ("ubuntu", "Linux", "aarch64", "neutrino-hub_9.9.9_arm64-cn.deb"),
        ("fedora", "Linux", "x86_64", "neutrino-hub-9.9.9-1.x86_64-cn.rpm"),
        ("arch", "Linux", "x86_64", "neutrino-hub-9.9.9-1-x86_64-cn.pkg.tar.zst"),
        ("ubuntu", "Darwin", "x86_64", "neutrino-hub-9.9.9-macos-amd64-cn.pkg"),
    ],
)
def test_a_cn_script_takes_the_cn_package_of_the_same_release(
    stand_ins, os_release, system, machine, name
):
    result, asked = stand_ins(
        edition="cn", os_release=os_release, system=system, machine=machine
    )

    assert result.returncode == 0, result.stderr
    (install,) = _installs(asked)
    assert f"/{name}" in install


def test_an_intl_script_never_takes_a_cn_package(stand_ins):
    (stand_ins.served / "neutrino-hub_9.9.9_amd64.deb").unlink()
    _write_sums(stand_ins.served)

    result, asked = stand_ins()

    assert result.returncode == 1
    assert _said(result) == (
        "The release publishes no Neutrino hub package for deb on amd64."
    )
    assert _installs(asked) == []


@from_intl_tree
@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_a_release_build_stamps_the_edition_and_the_sites(edition):
    text = install_script_stamp.stamped_text(
        SCRIPT.read_text(), RELATIVE, edition=edition, sites=PACKAGING_RELEASE_SITES
    )

    assert f'\nEDITION="{edition}"\n' in text
    sites = " ".join(
        f"{site['files']} {site['latest']}" for site in PACKAGING_RELEASE_SITES
    )
    assert f'\nRELEASE_SITES="{sites}"\n' in text
    assert sites.split()[0].startswith("https://github.com/")


@pytest.fixture(scope="module")
def mainland_tree(tmp_path_factory):
    """The mainland tree ``build_sources.py --edition cn --tree`` writes."""
    target = tmp_path_factory.mktemp("mainland") / "tree"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT.parents[1] / "build" / "build_sources.py"),
            "--edition",
            "cn",
            "--tree",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


@from_intl_tree
def test_the_mainland_tree_stamps_both_scripts_cn_with_the_sites(mainland_tree):
    install = mainland_tree / "packaging" / "install"
    shell = (install / "install.sh").read_text()
    powershell = (install / "install.ps1").read_text()

    assert '\nEDITION="cn"\n' in shell
    assert "\n$script:NeutrinoEdition = 'cn'\n" in powershell
    assert (
        f'\nRELEASE_SITES="{install_script_stamp.sites_text(RELATIVE, PACKAGING_RELEASE_SITES)}"\n'
        in shell
    )
    assert "\n$script:NeutrinoReleaseSites = @(@{ Files = 'https://github.com/" in (
        powershell
    )


@from_intl_tree
def test_the_mainland_script_installs_the_cn_package(stand_ins, mainland_tree):
    result, asked = stand_ins(
        edition=None, script=mainland_tree / "packaging" / "install" / "install.sh"
    )

    assert result.returncode == 0, result.stderr
    (install,) = _installs(asked)
    assert install.endswith("/neutrino-hub_9.9.9_amd64-cn.deb")


# --- one request for administrator rights ---


@pytest.mark.parametrize("component", ["hub", "agent", "client"])
@pytest.mark.parametrize(
    "system, machine, os_release",
    [
        ("Linux", "x86_64", "ubuntu"),
        ("Linux", "x86_64", "fedora"),
        ("Darwin", "arm64", "ubuntu"),
    ],
)
def test_a_run_asks_for_the_password_once_before_it_downloads(
    stand_ins, component, system, machine, os_release
):
    _publish_all(stand_ins.served)
    result, asked = stand_ins(
        component, system=system, machine=machine, os_release=os_release
    )

    assert result.returncode == 0, result.stderr
    assert asked[:2] == ["sudo -n true", "sudo -v"]
    assert asked.count("sudo -v") == 1
    assert result.stderr.count("asks for administrator rights once") == 1
    assert all(
        line.startswith(("sudo -n", "sudo installer", "sudo apt-get", "sudo dnf"))
        for line in asked[2:]
        if line.startswith("sudo")
    )


def test_root_is_asked_for_nothing(stand_ins):
    _result, asked = stand_ins("agent", uid="0")

    assert not any(line.startswith("sudo") for line in asked)


def test_a_refused_password_installs_nothing_and_downloads_nothing(stand_ins):
    result, asked = stand_ins(environment={"FAKE_SUDO_REFUSED": "1"})

    assert result.returncode == 1
    assert _said(result) == (
        "sudo did not grant administrator rights; nothing was installed."
    )
    assert asked == ["sudo -n true", "sudo -v"]


def test_a_system_with_no_package_asks_for_no_password(stand_ins):
    _result, asked = stand_ins(machine="armv7l")

    assert asked == []


@pytest.mark.parametrize(
    "component, uid, last",
    [
        (
            "agent",
            "1000",
            "Next, join this machine to a hub: sudo nagent join "
            "'<enrollment link from the hub's Agents page>'",
        ),
        (
            "agent",
            "0",
            "Next, join this machine to a hub: nagent join "
            "'<enrollment link from the hub's Agents page>'",
        ),
        (
            "client",
            "1000",
            "Next, join this computer to a hub: nclient hub join "
            "'<client link from the hub's Clients page>'",
        ),
    ],
)
def test_the_last_line_names_the_one_next_thing(stand_ins, component, uid, last):
    _publish_all(stand_ins.served)
    result, _asked = stand_ins(component, uid=uid)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == last


def test_the_hub_set_up_on_a_terminal_asks_nothing_again(tmp_path, stand_ins):
    """With a terminal the script runs setup itself, under the ticket it took."""
    script = SCRIPT.read_text()
    assert '\n        $as_root "$nhub" setup </dev/tty\n' in script
    assert script.index("hold_root") < script.index('"$nhub" setup')


@pytest.mark.parametrize("component", ["hub", "agent"])
def test_an_account_sudo_lets_in_without_a_password_is_asked_nothing(
    stand_ins, component
):
    _publish_all(stand_ins.served)
    result, asked = stand_ins(component, environment={"FAKE_SUDO_FREE": "1"})

    assert result.returncode == 0, result.stderr
    assert asked[0] == "sudo -n true"
    assert "sudo -v" not in asked
    assert "administrator rights" not in result.stderr


def test_the_keeper_refreshes_the_ticket_the_way_both_kinds_of_account_may():
    """``sudo -v`` asks an account that is password-free through one entry
    alone; running a command refreshes a ticket and needs none."""
    script = SCRIPT.read_text()
    keeper = script[script.index("hold_root() {") : script.index('echo "$!"')]

    assert "sudo -n true 2>/dev/null || exit 0" in keeper
    assert "sudo -n -v" not in keeper


@pytest.mark.parametrize(
    "system, machine, uid",
    [
        ("Linux", "x86_64", "1000"),
        ("Darwin", "arm64", "1000"),
        ("Linux", "x86_64", "0"),
    ],
)
def test_a_hub_already_set_up_is_upgraded_and_names_its_panel(
    stand_ins, system, machine, uid
):
    stand_ins.settings.write_text(SET_UP_SETTINGS)

    result, asked = stand_ins(
        system=system,
        machine=machine,
        uid=uid,
        environment={"FAKE_ADDRESS": "http://192.0.2.1:8080/"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "The hub was upgraded; its panel is at: http://192.0.2.1:8080/"
    )
    assert not any(" setup" in line for line in asked if "nhub" in line)


def test_a_hub_already_set_up_with_no_address_says_how_to_open_it(stand_ins):
    stand_ins.settings.write_text(SET_UP_SETTINGS)

    result, _asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "The hub was upgraded; sudo nhub open opens its panel."
    )


def test_a_hub_with_the_example_settings_is_not_set_up(stand_ins):
    stand_ins.settings.write_text(FRESH_SETTINGS)
    address = "http://192.0.2.1:8080/?token=t0ken"

    result, _asked = stand_ins(environment={"FAKE_ADDRESS": address})

    assert result.stdout.strip().splitlines()[-1] == (
        f"Next, set the hub up in a browser at: {address}"
    )


def test_root_without_the_hubs_folder_on_its_path_reaches_nhub(stand_ins):
    """The fake nhub is on no PATH entry: only its whole name reaches it."""
    address = "http://192.0.2.1:8080/?token=t0ken"

    result, asked = stand_ins(uid="0", environment={"FAKE_ADDRESS": address})

    assert result.returncode == 0, result.stderr
    assert "nhub open --print" in asked
    assert result.stdout.strip().splitlines()[-1].endswith(address)


def test_the_script_names_the_hub_where_its_packages_put_it():
    from neutrino_hub.cli.password import PASSWORD_SETTINGS_FILE
    from neutrino_hub.platforms.constants import (
        PLATFORM_OS_DARWIN,
        PLATFORM_OS_LINUX,
        PLATFORM_ROOT_CONFIG,
        PLATFORM_ROOTS,
    )

    text = SCRIPT.read_text()
    linux = f"{PLATFORM_ROOTS[PLATFORM_OS_LINUX][PLATFORM_ROOT_CONFIG]}/{PASSWORD_SETTINGS_FILE}"
    darwin = f"{PLATFORM_ROOTS[PLATFORM_OS_DARWIN][PLATFORM_ROOT_CONFIG]}/{PASSWORD_SETTINGS_FILE}"
    assert f"\nHUB_SETTINGS_LINUX={linux}\n" in text
    assert f'\nHUB_SETTINGS_MACOS="{darwin}"\n' in text
    assert "\nHUB_COMMAND_LINUX=/usr/bin/nhub\n" in text
    assert "\nHUB_COMMAND_MACOS=/usr/local/bin/nhub\n" in text
    for line in text.splitlines():
        assert not re.search(r"\$as_root( \$\{as_root:\+-n\})? nhub ", line), line


def _publish_all(served):
    """Every component for a deb, an rpm and an Apple silicon Mac."""
    for component in ("hub", "agent", "client"):
        for name in (
            f"neutrino-{component}_9.9.9_amd64.deb",
            f"neutrino-{component}-9.9.9-1.x86_64.rpm",
            f"neutrino-{component}-9.9.9-macos-arm64.pkg",
        ):
            (served / name).write_bytes(name.encode())
    lines = []
    for path in sorted(served.iterdir()):
        if path.name == "SHA256SUMS":
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (served / "SHA256SUMS").write_text("\n".join(lines) + "\n")


# --- a machine that has joined is not told to join ---

BINDING = (
    '{\n  "gateway_url": "tcp://hub:8443",\n  "id": "d1",\n  "token": "t0k",'
    '\n  "hub_key": "k3y"\n}\n'
)
# What an agent of 0.5 left: a certificate fingerprint and no hub key.
BINDING_05 = (
    '{\n  "gateway_url": "https://hub:8443",\n  "id": "d1",\n  "token": "t0k",'
    '\n  "fingerprint": "AB:CD"\n}\n'
)


@pytest.mark.parametrize("system, machine", [("Linux", "x86_64"), ("Darwin", "arm64")])
def test_a_joined_machine_is_given_no_join_line(stand_ins, tmp_path, system, machine):
    _publish_all(stand_ins.served)
    (tmp_path / "agent.json").write_text(BINDING)

    result, asked = stand_ins("agent", system=system, machine=machine)

    assert result.returncode == 0, result.stderr
    assert "nagent join" not in result.stdout
    assert result.stdout.splitlines()[-1].startswith("Installed neutrino-agent")
    assert any("grep -Eq" in line for line in asked if line.startswith("sudo -n"))


def test_a_binding_without_its_token_is_no_binding(stand_ins, tmp_path):
    _publish_all(stand_ins.served)
    (tmp_path / "agent.json").write_text('{\n  "token": ""\n}\n')

    result, _asked = stand_ins("agent")

    assert (
        result.stdout.strip()
        .splitlines()[-1]
        .startswith("Next, join this machine to a hub: ")
    )


def test_a_binding_of_0_5_is_no_binding(stand_ins, tmp_path):
    _publish_all(stand_ins.served)
    (tmp_path / "agent.json").write_text(BINDING_05)

    result, _asked = stand_ins("agent")

    assert (
        result.stdout.strip()
        .splitlines()[-1]
        .startswith("Next, join this machine to a hub: ")
    )


def test_the_script_reads_the_binding_where_the_agent_writes_it():
    sys.path.insert(0, str(SCRIPT.parents[2] / "agent"))
    constants = "agent/neutrino_agent/constants.py"
    AGENT_CONFIG_NAME = _stated(constants, "AGENT_CONFIG_NAME")
    AGENT_DATA_DIR_DARWIN = _stated(constants, "AGENT_DATA_DIR_DARWIN")
    AGENT_DATA_DIR_POSIX = _stated(constants, "AGENT_DATA_DIR_POSIX")

    text = SCRIPT.read_text()
    linux = os.path.join(AGENT_DATA_DIR_POSIX, AGENT_CONFIG_NAME)
    darwin = os.path.join(AGENT_DATA_DIR_DARWIN, AGENT_CONFIG_NAME)
    assert f"\nAGENT_BINDING_LINUX={linux}\n" in text
    assert f'\nAGENT_BINDING_MACOS="{darwin}"\n' in text


# --- a person who has joined is not told to join ---

CLIENT_BINDINGS = (
    '{\n  "bindings": [{"id": "c1", "token": "t0k", "hub_key": "k3y",'
    ' "gateway_urls": ["tcp://hub:8443"]}],\n  "exit_hub_id": ""\n}\n'
)
# What a client of 0.5 left: a certificate fingerprint and no hub key.
CLIENT_BINDINGS_05 = (
    '{\n  "bindings": [{"id": "c1", "token": "t0k", "fingerprint": "AB:CD",'
    ' "urls": ["https://hub:8443"]}],\n  "exit_hub_id": ""\n}\n'
)
CLIENT_JOIN_LINE = (
    "Next, join this computer to a hub: nclient hub join "
    "'<client link from the hub's Clients page>'"
)
CLIENT_BINDINGS_PLACES = {
    "Linux": ".config/neutrino/client/client.json",
    "Darwin": "Library/Application Support/Neutrino/client/client.json",
}


def _bind_client(home, system, text=CLIENT_BINDINGS):
    bindings = home / CLIENT_BINDINGS_PLACES[system]
    bindings.parent.mkdir(parents=True, exist_ok=True)
    bindings.write_text(text)


@pytest.mark.parametrize("system, machine", [("Linux", "x86_64"), ("Darwin", "arm64")])
def test_a_person_who_has_joined_is_given_no_join_line(
    stand_ins, tmp_path, system, machine
):
    _publish_all(stand_ins.served)
    _bind_client(tmp_path, system)

    result, _asked = stand_ins("client", system=system, machine=machine)

    assert result.returncode == 0, result.stderr
    assert "nclient hub join" not in result.stdout


def test_a_client_binding_without_its_token_is_no_binding(stand_ins, tmp_path):
    _publish_all(stand_ins.served)
    _bind_client(tmp_path, "Linux", '{\n  "bindings": [{"token": ""}]\n}\n')

    result, _asked = stand_ins("client")

    assert result.stdout.strip().splitlines()[-1] == CLIENT_JOIN_LINE


def test_a_client_binding_of_0_5_is_no_binding(stand_ins, tmp_path):
    _publish_all(stand_ins.served)
    _bind_client(tmp_path, "Linux", CLIENT_BINDINGS_05)

    result, _asked = stand_ins("client")

    assert result.stdout.strip().splitlines()[-1] == CLIENT_JOIN_LINE


def test_the_bindings_are_read_where_xdg_config_home_puts_them(stand_ins, tmp_path):
    _publish_all(stand_ins.served)
    config = tmp_path / "elsewhere"
    (config / "neutrino/client").mkdir(parents=True)
    (config / "neutrino/client/client.json").write_text(CLIENT_BINDINGS)

    result, _asked = stand_ins("client", environment={"XDG_CONFIG_HOME": str(config)})

    assert "nclient hub join" not in result.stdout


@pytest.mark.parametrize("is_bound", [True, False])
def test_through_sudo_the_invoking_persons_own_bindings_decide(
    stand_ins, tmp_path, is_bound
):
    """Root's own home holds nothing; the person sudo names does or does not."""
    _publish_all(stand_ins.served)
    person = tmp_path / "alice"
    if is_bound:
        _bind_client(person, "Linux")

    result, _asked = stand_ins(
        "client",
        uid="0",
        environment={
            "SUDO_USER": "alice",
            "FAKE_SUDO_USER_NAME": "alice",
            "FAKE_SUDO_USER_HOME": str(person),
        },
    )

    assert result.returncode == 0, result.stderr
    if is_bound:
        assert "nclient hub join" not in result.stdout
    else:
        assert result.stdout.strip().splitlines()[-1] == CLIENT_JOIN_LINE


def _stated(relative, name):
    """A path constant as a module of the repository states it, read from its
    source, so the hub's tests need neither the agent nor the client
    installed; ``os.path.join`` of literals reads as their ``/`` join."""
    import ast

    source = (SCRIPT.parents[2] / relative).read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == name for target in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Call):
                return "/".join(ast.literal_eval(part) for part in value.args)
            return ast.literal_eval(value)
    raise AssertionError(f"{relative} states no {name}")


def test_the_script_reads_the_bindings_where_the_client_writes_them():
    client = "client/desktop/neutrino_client"
    CLIENT_CONFIG_FILE_NAME = _stated(
        f"{client}/constants.py", "CLIENT_CONFIG_FILE_NAME"
    )
    DARWIN_CONFIG_DIR = _stated(f"{client}/platforms/darwin.py", "DARWIN_CONFIG_DIR")
    CONFIG_DIR_NAME = _stated(f"{client}/platforms/linux.py", "CONFIG_DIR_NAME")

    text = SCRIPT.read_text()
    linux = f".config/{CONFIG_DIR_NAME}/{CLIENT_CONFIG_FILE_NAME}"
    darwin = f"{DARWIN_CONFIG_DIR}/{CLIENT_CONFIG_FILE_NAME}"
    assert f"\nCLIENT_BINDINGS_LINUX={linux}\n" in text
    assert f'\nCLIENT_BINDINGS_MACOS="{darwin}"\n' in text


# --- another program holding the package manager ---


def _holder(run, pid, comm, *words):
    """One process as the kernel shows it: its cut name and its command line."""
    directory = run.proc / str(pid)
    directory.mkdir(parents=True)
    (directory / "comm").write_text(comm + "\n")
    (directory / "cmdline").write_bytes(b"\0".join(words) + b"\0")


def _hold_dpkg(run, pid, lock=None):
    """One of apt's locks held by a process, as /proc/locks lists it."""
    inode = os.stat(run.dpkg_lock if lock is None else lock).st_ino
    run.locks.write_text(f"1: POSIX  ADVISORY  WRITE {pid} 08:01:{inode} 0 EOF\n")


def _later(seconds, action):
    """Run an action on a thread after a while, as a holder finishing."""
    timer = threading.Timer(seconds, action)
    timer.start()
    return timer


def test_an_install_waits_for_dpkg_s_holder_naming_it_whole(stand_ins):
    _holder(
        stand_ins,
        4242,
        "unattended-upgr",
        b"/usr/bin/python3",
        b"/usr/bin/unattended-upgrade",
        b"--download-only",
    )
    _hold_dpkg(stand_ins, 4242)
    released = _later(1.5, lambda: stand_ins.locks.write_text(""))

    result, asked = stand_ins("agent")
    released.join()

    assert result.returncode == 0, result.stderr
    waiting = [line for line in result.stdout.splitlines() if "Waiting" in line]
    assert waiting == [
        "Waiting up to 300 seconds for unattended-upgrade (process 4242) "
        "to finish with the package manager"
    ]
    (install,) = _installs(asked)
    assert install.startswith("apt-get install -y -o DPkg::Lock::Timeout=300 /")


def test_an_install_waits_for_apt_get_update_writing_the_package_lists(stand_ins):
    """A fresh machine's cloud-init runs apt-get update first: apt-get
    install on lists half written finds none of the package's
    dependencies."""
    _holder(stand_ins, 1646, "apt-get", b"/usr/bin/apt-get", b"--assume-yes", b"update")
    _hold_dpkg(stand_ins, 1646, stand_ins.lists_lock)
    released = _later(1.5, lambda: stand_ins.locks.write_text(""))

    result, asked = stand_ins("agent")
    released.join()

    assert result.returncode == 0, result.stderr
    assert (
        "Waiting up to 300 seconds for apt-get (process 1646) to finish with the "
        "package manager"
    ) in result.stdout.splitlines()
    assert len(_installs(asked)) == 1


def test_a_package_manager_held_past_the_wait_installs_nothing(stand_ins):
    _holder(stand_ins, 4242, "apt-get", b"apt-get", b"install", b"-y", b"x")
    _hold_dpkg(stand_ins, 4242)

    result, asked = stand_ins("agent", lock_wait_s=2)

    assert result.returncode == 1
    assert _said(result) == (
        "apt-get (process 4242) still holds the package manager after 2 seconds; "
        "nothing was installed. Run this script again once it has finished."
    )
    assert _installs(asked) == []


def test_an_install_waits_for_the_holder_of_dnf_s_own_lock(stand_ins):
    _holder(
        stand_ins,
        4343,
        "dnf-automatic",
        b"/usr/bin/python3",
        b"-s",
        b"/usr/bin/dnf-automatic",
        b"--timer",
    )
    stand_ins.dnf_lock.write_text("4343")
    released = _later(1.5, lambda: stand_ins.dnf_lock.unlink())

    result, asked = stand_ins("agent", os_release="rocky")
    released.join()

    assert result.returncode == 0, result.stderr
    waiting = [line for line in result.stdout.splitlines() if "Waiting" in line]
    assert waiting == [
        "Waiting up to 300 seconds for dnf-automatic (process 4343) "
        "to finish with the package manager"
    ]
    assert _installs(asked)[-1].startswith("dnf install -y /")


def test_a_dnf_lock_file_of_an_ended_process_holds_nothing(stand_ins):
    stand_ins.dnf_lock.write_text("4343")

    result, _ = stand_ins("agent", os_release="fedora")

    assert result.returncode == 0, result.stderr
    assert "Waiting" not in result.stdout


def test_dnf_5_runs_again_while_another_transaction_holds_the_rpm_lock(
    stand_ins, tmp_path
):
    locked = tmp_path / "dnf_locked"
    locked.write_text("1\n2\n")

    result, asked = stand_ins(
        "agent", os_release="fedora", environment={"FAKE_DNF_LOCKED": str(locked)}
    )

    assert result.returncode == 0, result.stderr
    assert (
        "Waiting up to 300 seconds for another transaction to finish with the "
        "package manager"
    ) in result.stdout.splitlines()
    assert len([line for line in _installs(asked) if line.startswith("dnf")]) == 3
