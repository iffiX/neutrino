"""The one-command installer for macOS and Linux, run against stand-ins.

``install.sh`` runs under ``sh`` with ``uname``, ``id``, ``curl``, ``sudo``
and every package manager replaced by scripts that record what they were
asked, so what is asserted is the package each system and machine takes,
the command that installs it, the release it comes from, the checksum that
stops a wrong file, and the one sentence each refusal prints.
"""

import hashlib
import sys
import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "install" / "install.sh"

RELEASE = "https://github.com/iffiX/neutrino/releases"
CN_RELEASE = "https://gitee.com/iffiX/neutrino/releases"
CN_LATEST = "https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest"

PACKAGES = (
    "neutrino-hub_9.9.9_amd64.deb",
    "neutrino-hub_9.9.9_arm64.deb",
    "neutrino-agent_9.9.9_amd64.deb",
    "neutrino-hub-9.9.9-1.x86_64.rpm",
    "neutrino-hub-9.9.9-1.aarch64.rpm",
    "neutrino-hub-9.9.9-1-x86_64.pkg.tar.zst",
    "neutrino-hub-9.9.9-macos-arm64.pkg",
    "neutrino-hub-9.9.9-macos-amd64.pkg",
    "neutrino-client-9.9.9-macos-amd64.pkg",
    "neutrino-hub-9.9.9-windows-amd64.msi",
    "install.sh",
)

OS_RELEASES = {
    "ubuntu": 'ID=ubuntu\nID_LIKE="debian"\nVERSION_ID="24.04"\n',
    "fedora": 'ID=fedora\nVERSION_ID="41"\n',
    "rocky": 'ID="rocky"\nID_LIKE="rhel centos fedora"\n',
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
exec "$@"
""",
    "curl": """#!/bin/sh
for argument in "$@"; do
    case "$previous" in -o) target=$argument ;; esac
    previous=$argument
    url=$argument
done
echo "curl $url" >> "$FAKE_LOG"
served="$FAKE_SERVED/$(basename "$url")"
[ -f "$served" ] || exit 22
cp "$served" "$target"
""",
    "installer": RECORDER,
    "apt-get": RECORDER,
    "dnf": RECORDER,
    "pacman": RECORDER,
    "nhub": """#!/bin/sh
echo "nhub $*" >> "$FAKE_LOG"
if [ -n "$FAKE_ADDRESS" ]; then echo "$FAKE_ADDRESS"; fi
""",
}


@pytest.fixture
def stand_ins(tmp_path):
    """The fakes on the path, a release of fake packages, and how to run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in FAKES.items():
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    served = tmp_path / "release"
    served.mkdir()
    lines = []
    for name in PACKAGES:
        (served / name).write_bytes(name.encode())
        lines.append(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}")
    (served / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    log = tmp_path / "log"

    def run(
        *arguments,
        system="Linux",
        machine="x86_64",
        os_release="ubuntu",
        uid="1000",
        environment=None,
        edition="intl",
        script=SCRIPT,
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
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FAKE_LOG": str(log),
            "FAKE_SERVED": str(served),
            "FAKE_SYSTEM": system,
            "FAKE_MACHINE": machine,
            "FAKE_UID": uid,
            "HOME": str(tmp_path),
            **(environment or {}),
        }
        result = subprocess.run(
            [
                "sh",
                "-c",
                f'. "{functions}"; OS_RELEASE="{release_file}"; main "$@"',
                "install.sh",
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        asked = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return result, asked

    run.served = served
    return run


def _installs(asked):
    return [line for line in asked if not line.startswith(("curl", "sudo", "nhub"))]


def test_the_script_is_posix_sh_and_ends_by_running_main():
    result = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert SCRIPT.read_text().startswith("#!/bin/sh\n")
    assert os.access(SCRIPT, os.X_OK)


def test_a_debian_machine_installs_the_hub_deb_from_the_latest_release(stand_ins):
    result, asked = stand_ins()

    assert result.returncode == 0, result.stderr
    assert asked[:2] == [
        f"curl {RELEASE}/latest/download/SHA256SUMS",
        f"curl {RELEASE}/latest/download/neutrino-hub_9.9.9_amd64.deb",
    ]
    (install,) = _installs(asked)
    assert install.startswith("apt-get install -y /")
    assert install.endswith("/neutrino-hub_9.9.9_amd64.deb")
    assert "sudo apt-get install -y" in asked[2]


def test_a_pinned_version_comes_from_that_release(stand_ins):
    _result, asked = stand_ins(environment={"NEUTRINO_VERSION": "v9.9.9"})

    assert asked[0] == f"curl {RELEASE}/download/v9.9.9/SHA256SUMS"
    assert asked[1] == f"curl {RELEASE}/download/v9.9.9/neutrino-hub_9.9.9_amd64.deb"


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
        ("ubuntu", "aarch64", "apt-get install -y", "neutrino-hub_9.9.9_arm64.deb"),
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
    (install,) = _installs(asked)
    assert install.startswith(command + " /")
    assert install.endswith("/" + name)


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

    assert f"Set the hub up in a browser at: {address}" in result.stdout
    assert "nhub open --print" in asked
    assert not any(line.startswith("nhub setup") for line in asked)


def test_without_an_address_the_hub_says_how_to_open_the_wizard(stand_ins):
    result, _asked = stand_ins(system="Darwin", machine="arm64")

    assert "Set the hub up with: sudo nhub open" in result.stdout


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
    assert not any(line.startswith("curl") for line in asked)
    (install,) = _installs(asked)
    assert f"{stand_ins.served}/neutrino-client-9.9.9-macos-amd64.pkg" in install


def test_a_package_that_does_not_match_its_checksum_is_never_installed(stand_ins):
    (stand_ins.served / "neutrino-hub_9.9.9_amd64.deb").write_bytes(b"tampered")

    result, asked = stand_ins()

    assert result.returncode == 1
    assert result.stderr.strip() == (
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
    assert result.stderr.strip() == said
    assert _installs(asked) == []


def test_a_release_that_cannot_be_reached_stops_with_one_sentence(stand_ins):
    (stand_ins.served / "SHA256SUMS").unlink()

    result, _asked = stand_ins()

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"Downloading {RELEASE}/latest/download/SHA256SUMS failed."
    )


def test_the_script_names_the_edition_of_its_tree():
    edition = (SCRIPT.parents[2] / "EDITION").read_text().strip()

    assert f'\nEDITION="{edition}"\n' in SCRIPT.read_text()


def test_a_cn_script_reads_the_latest_tag_from_gitee_then_its_files(stand_ins):
    (stand_ins.served / "latest").write_text(
        '{"id":7,"tag_name":"v9.9.9","name":"v9.9.9","assets":[]}'
    )

    result, asked = stand_ins(edition="cn")

    assert result.returncode == 0, result.stderr
    assert asked[:3] == [
        f"curl {CN_LATEST}",
        f"curl {CN_RELEASE}/download/v9.9.9/SHA256SUMS",
        f"curl {CN_RELEASE}/download/v9.9.9/neutrino-hub_9.9.9_amd64.deb",
    ]
    (install,) = _installs(asked)
    assert install.endswith("/neutrino-hub_9.9.9_amd64.deb")


def test_a_cn_script_given_a_version_asks_the_api_nothing(stand_ins):
    result, asked = stand_ins(edition="cn", environment={"NEUTRINO_VERSION": "v9.9.9"})

    assert result.returncode == 0, result.stderr
    assert asked[0] == f"curl {CN_RELEASE}/download/v9.9.9/SHA256SUMS"


def test_a_cn_latest_release_with_no_tag_stops_with_one_sentence(stand_ins):
    (stand_ins.served / "latest").write_text("null")

    result, asked = stand_ins(edition="cn")

    assert result.returncode == 1
    assert result.stderr.strip() == (f"The latest release at {CN_LATEST} names no tag.")
    assert _installs(asked) == []


def test_a_cn_release_with_its_files_not_yet_uploaded_stops_with_one_sentence(
    stand_ins,
):
    (stand_ins.served / "latest").write_text('{"tag_name": "v9.9.9"}')
    (stand_ins.served / "SHA256SUMS").unlink()

    result, asked = stand_ins(edition="cn")

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"Downloading {CN_RELEASE}/download/v9.9.9/SHA256SUMS failed."
    )
    assert _installs(asked) == []


# The mainland tree is written from the intl checkout, and from nothing else.
from_intl_tree = pytest.mark.skipif(
    (Path(__file__).resolve().parents[3] / "EDITION").read_text().strip() != "intl",
    reason="the mainland tree is written from the intl checkout",
)


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
def test_the_mainland_tree_stamps_both_scripts_cn(mainland_tree):
    install = mainland_tree / "packaging" / "install"

    assert '\nEDITION="cn"\n' in (install / "install.sh").read_text()
    assert "\n$script:NeutrinoEdition = 'cn'\n" in (install / "install.ps1").read_text()


@from_intl_tree
def test_the_mainland_script_installs_from_gitee(stand_ins, mainland_tree):
    (stand_ins.served / "latest").write_text('{"tag_name": "v9.9.9"}')

    result, asked = stand_ins(
        edition=None, script=mainland_tree / "packaging" / "install" / "install.sh"
    )

    assert result.returncode == 0, result.stderr
    assert asked[:3] == [
        f"curl {CN_LATEST}",
        f"curl {CN_RELEASE}/download/v9.9.9/SHA256SUMS",
        f"curl {CN_RELEASE}/download/v9.9.9/neutrino-hub_9.9.9_amd64.deb",
    ]
