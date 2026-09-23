"""Staging a package and handing the install to systemd, with nothing real."""

import hashlib
import io
import subprocess
from collections import namedtuple
from pathlib import Path

import pytest

from neutrino_hub.exceptions import HubUpdateError
from neutrino_hub.modules.hub_update import installer as installer_module
from neutrino_hub.modules.hub_update.installer import (
    HubUpdateInstaller,
    HubUpdatePlan,
    check_space,
    free_bytes,
    install_commands,
    render_script,
    space_needed,
)
from neutrino_hub.modules.hub_update.release import HubRelease
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile

ASSET = "neutrino-hub_{version}_amd64.deb"
Usage = namedtuple("Usage", "total used free")


def release(version: str, payload: bytes) -> HubRelease:
    name = ASSET.format(version=version)
    return HubRelease(
        version=version,
        tag=f"v{version}",
        published_at="2026-10-01T12:00:00Z",
        notes="",
        page_url="",
        asset_name=name,
        asset_url=f"https://example.invalid/{name}",
        asset_size=len(payload),
        checksums_url=f"https://example.invalid/v{version}/SHA256SUMS",
    )


class Checker:
    """Releases and digests answered from what a test declares."""

    def __init__(self, *, latest=None, by_version=None, digests=None):
        self.latest_release = latest
        self.by_version = by_version or {}
        self.digests = digests or {}
        self.asked = []

    def latest(self):
        return self.latest_release

    def for_version(self, version):
        self.asked.append(version)
        return self.by_version.get(version)

    def digest_of(self, found):
        return self.digests[found.asset_name]


class Stream(io.BytesIO):
    """A download that closes like a response."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def roots(monkeypatch, tmp_path):
    """The state and static roots under the test's directory, one device."""
    state = tmp_path / "state"
    static = tmp_path / "static"
    state.mkdir()
    static.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATIC_ROOT", static)
    return state, static


def make_installer(tmp_path, *, checker, payloads=None, units=None, launched=None):
    """An installer whose network, systemd and disk are the test's."""
    payloads = payloads or {}
    launched = launched if launched is not None else []

    def open_url(url):
        if url not in payloads:
            raise OSError(f"no route to {url}")
        return Stream(payloads[url])

    def run_command(command, **keywords):
        launched.append((command, keywords))

    return HubUpdateInstaller(
        checker=checker,
        state=HubUpdateStateFile(path=tmp_path / "state" / "hub_update" / "state.json"),
        asset=ASSET,
        family="debian",
        open_url=open_url,
        run_command=run_command,
        unit_state_of=lambda unit: (units or {}).get(unit, "inactive"),
        disk_usage=lambda path: Usage(10**12, 0, 10**12),
    )


# --- room on the disk ---


def test_room_is_counted_once_when_both_roots_share_a_filesystem(roots):
    state, static = roots

    assert space_needed(100, is_rollback_fetched=False) == {state: 400}
    assert space_needed(100, is_rollback_fetched=True) == {state: 500}


def test_room_is_counted_per_root_when_they_are_on_different_filesystems(
    roots, monkeypatch
):
    state, static = roots
    monkeypatch.setattr(
        installer_module, "_device_of", lambda path: 1 if path == state else 2
    )

    assert space_needed(100, is_rollback_fetched=True) == {state: 200, static: 300}


def test_too_little_room_is_refused_with_the_numbers(roots):
    state, _ = roots

    with pytest.raises(HubUpdateError) as refused:
        check_space(
            100, is_rollback_fetched=False, disk_usage=lambda path: Usage(1, 1, 399)
        )

    assert refused.value.code == "disk_space_short"
    assert refused.value.params == {
        "path": str(state),
        "needed_bytes": 400,
        "free_bytes": 399,
    }


def test_enough_room_passes(roots):
    check_space(
        100, is_rollback_fetched=False, disk_usage=lambda path: Usage(1, 1, 400)
    )


def test_the_numbers_shown_are_the_tightest_roots(roots, monkeypatch):
    state, static = roots
    monkeypatch.setattr(
        installer_module, "_device_of", lambda path: 1 if path == state else 2
    )
    usage = {state: Usage(1, 1, 10_000), static: Usage(1, 1, 301)}

    assert free_bytes(100, is_rollback_fetched=True, disk_usage=usage.get) == (300, 301)


# --- what each family runs ---


def test_debian_installs_and_rolls_back_with_one_apt_line():
    install, rollback = install_commands("debian", Path("/x/a b.deb"))

    assert install == (
        "$PACE apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=300 '/x/a b.deb'"
    )
    assert rollback == install


def test_rhel_reinstalls_forward_and_puts_the_old_package_back_with_rpm():
    install, rollback = install_commands("rhel", Path("/x/a.rpm"))

    assert install == (
        "$PACE dnf reinstall -y /x/a.rpm || $PACE dnf install -y /x/a.rpm"
    )
    assert rollback == "$PACE rpm -Uvh --oldpackage /x/a.rpm"


def test_arch_takes_the_file_both_ways():
    assert install_commands("arch", Path("/x/a.pkg.tar.zst")) == (
        "$PACE pacman -U --noconfirm /x/a.pkg.tar.zst",
        "$PACE pacman -U --noconfirm /x/a.pkg.tar.zst",
    )


def test_an_unknown_family_has_no_command():
    with pytest.raises(ValueError):
        install_commands("suse", Path("/x/a.rpm"))


# --- staging ---


def test_staging_downloads_the_package_and_checks_its_digest(tmp_path, roots):
    payload = b"new package bytes"
    wanted = release("0.3.1", payload)
    checker = Checker(digests={wanted.asset_name: hashlib.sha256(payload).hexdigest()})
    installer = make_installer(
        tmp_path, checker=checker, payloads={wanted.asset_url: payload}
    )
    lines = []

    plan = installer.prepare(
        wanted, current="0.3.0", port=8080, on_progress=lines.append
    )

    assert plan.package == roots[0] / "hub_update" / wanted.asset_name
    assert plan.package.read_bytes() == payload
    assert plan.package.stat().st_mode & 0o777 == 0o644
    assert (roots[0] / "hub_update").stat().st_mode & 0o777 == 0o755
    assert plan.from_version == "0.3.0"
    assert plan.to_version == "0.3.1"
    assert plan.family == "debian"
    assert plan.port == 8080
    assert plan.started_at.endswith("Z")
    assert lines[0].startswith("downloading neutrino-hub_0.3.1_amd64.deb")
    assert "100%" in lines
    assert "the package matches its published digest" in lines


def test_a_package_whose_digest_differs_is_deleted_and_refused(tmp_path, roots):
    wanted = release("0.3.1", b"tampered")
    checker = Checker(digests={wanted.asset_name: "0" * 64})
    installer = make_installer(
        tmp_path, checker=checker, payloads={wanted.asset_url: b"tampered"}
    )

    with pytest.raises(HubUpdateError) as refused:
        installer.prepare(wanted, current="0.3.0", port=8080)

    assert refused.value.code == "package_sha256_mismatch"
    assert not list((roots[0] / "hub_update").glob("*.deb"))
    assert not list((roots[0] / "hub_update").glob(".tmp_*"))


def test_a_download_that_breaks_leaves_nothing_behind(tmp_path, roots):
    wanted = release("0.3.1", b"x" * 10)
    checker = Checker(digests={wanted.asset_name: "0" * 64})
    installer = make_installer(tmp_path, checker=checker, payloads={})

    with pytest.raises(HubUpdateError) as refused:
        installer.prepare(wanted, current="0.3.0", port=8080)

    assert refused.value.code == "package_fetch_failed"
    assert not list((roots[0] / "hub_update").iterdir())


def test_a_package_already_here_that_matches_is_not_downloaded_again(tmp_path, roots):
    payload = b"already here"
    wanted = release("0.3.1", payload)
    directory = roots[0] / "hub_update"
    directory.mkdir()
    (directory / wanted.asset_name).write_bytes(payload)
    checker = Checker(digests={wanted.asset_name: hashlib.sha256(payload).hexdigest()})
    installer = make_installer(tmp_path, checker=checker, payloads={})
    lines = []

    plan = installer.prepare(
        wanted, current="0.3.0", port=8080, on_progress=lines.append
    )

    assert plan.package.read_bytes() == payload
    assert lines[0].endswith("is already here and matches its digest")


def test_staging_keeps_only_the_target_and_the_rollback(tmp_path, roots):
    payload = b"new"
    wanted = release("0.3.1", payload)
    directory = roots[0] / "hub_update"
    directory.mkdir()
    for name in ("neutrino-hub_0.2.9_amd64.deb", "neutrino-hub_0.3.0_amd64.deb"):
        (directory / name).write_bytes(b"old")
    (directory / "update.log").write_text("old log")
    (directory / "update.sh").write_text("old script")
    (directory / ".tmp_leftover").write_bytes(b"half")
    checker = Checker(digests={wanted.asset_name: hashlib.sha256(payload).hexdigest()})
    installer = make_installer(
        tmp_path, checker=checker, payloads={wanted.asset_url: payload}
    )

    plan = installer.prepare(wanted, current="0.3.0", port=8080)

    assert sorted(entry.name for entry in directory.iterdir()) == [
        "neutrino-hub_0.3.0_amd64.deb",
        "neutrino-hub_0.3.1_amd64.deb",
    ]
    assert plan.rollback == directory / "neutrino-hub_0.3.0_amd64.deb"


def test_the_rollback_is_fetched_from_the_running_versions_release(tmp_path, roots):
    new = b"new"
    old = b"old"
    wanted = release("0.3.1", new)
    previous = release("0.3.0", old)
    checker = Checker(
        by_version={"0.3.0": previous},
        digests={
            wanted.asset_name: hashlib.sha256(new).hexdigest(),
            previous.asset_name: hashlib.sha256(old).hexdigest(),
        },
    )
    installer = make_installer(
        tmp_path,
        checker=checker,
        payloads={wanted.asset_url: new, previous.asset_url: old},
    )
    lines = []

    plan = installer.prepare(
        wanted, current="0.3.0", port=8080, on_progress=lines.append
    )

    assert plan.rollback.read_bytes() == old
    assert checker.asked == ["0.3.0"]
    assert "the rollback package matches its published digest" in lines


def test_no_release_for_the_running_version_means_no_rollback(tmp_path, roots):
    new = b"new"
    wanted = release("0.3.1", new)
    checker = Checker(digests={wanted.asset_name: hashlib.sha256(new).hexdigest()})
    installer = make_installer(
        tmp_path, checker=checker, payloads={wanted.asset_url: new}
    )
    lines = []

    plan = installer.prepare(
        wanted, current="0.3.0", port=8080, on_progress=lines.append
    )

    assert plan.rollback is None
    assert any("there is no rollback" in line for line in lines)


def test_a_rollback_a_release_carries_but_cannot_be_fetched_refuses(tmp_path, roots):
    new = b"new"
    wanted = release("0.3.1", new)
    previous = release("0.3.0", b"old")
    checker = Checker(
        by_version={"0.3.0": previous},
        digests={
            wanted.asset_name: hashlib.sha256(new).hexdigest(),
            previous.asset_name: "0" * 64,
        },
    )
    installer = make_installer(
        tmp_path,
        checker=checker,
        payloads={wanted.asset_url: new, previous.asset_url: b"old"},
    )

    with pytest.raises(HubUpdateError) as refused:
        installer.prepare(wanted, current="0.3.0", port=8080)

    assert refused.value.code == "rollback_fetch_failed"
    assert not (roots[0] / "hub_update" / previous.asset_name).exists()


def test_too_little_room_refuses_before_anything_is_fetched(tmp_path, roots):
    wanted = release("0.3.1", b"x" * 100)
    installer = make_installer(tmp_path, checker=Checker(), payloads={})
    installer._disk_usage = lambda path: Usage(1, 1, 10)

    with pytest.raises(HubUpdateError) as refused:
        installer.prepare(wanted, current="0.3.0", port=8080)

    assert refused.value.code == "disk_space_short"


def test_the_gate_holds_for_the_panel_and_whatever_of_the_routers_is_running(
    tmp_path, roots
):
    new = b"new"
    wanted = release("0.3.1", new)
    checker = Checker(digests={wanted.asset_name: hashlib.sha256(new).hexdigest()})
    installer = make_installer(
        tmp_path,
        checker=checker,
        payloads={wanted.asset_url: new},
        units={"neutrino_hub_router": "active", "neutrino_hub_dnsmasq": "inactive"},
    )

    plan = installer.prepare(wanted, current="0.3.0", port=8080)

    assert plan.units == ("neutrino_hub_web", "neutrino_hub_router")


def test_rollback_availability_is_the_file_or_a_release(tmp_path, roots):
    previous = release("0.3.0", b"old")
    installer = make_installer(tmp_path, checker=Checker())
    assert installer.is_rollback_available("0.3.0") is False

    installer = make_installer(
        tmp_path, checker=Checker(by_version={"0.3.0": previous})
    )
    assert installer.is_rollback_available("0.3.0") is True

    directory = roots[0] / "hub_update"
    directory.mkdir()
    (directory / previous.asset_name).write_bytes(b"old")
    installer = make_installer(tmp_path, checker=Checker())
    assert installer.is_rollback_available("0.3.0") is True
    assert installer.is_rollback_present("0.3.0") is True


# --- a file somebody brought ---


def test_a_package_file_is_linked_in_and_its_version_read_off_its_name(tmp_path, roots):
    """On one filesystem the staged file is the brought one, not a second
    copy written to the card just before the unpack writes the next."""
    brought = tmp_path / "neutrino-hub_0.3.1_amd64.deb"
    brought.write_bytes(b"brought")
    installer = make_installer(tmp_path, checker=Checker())
    lines = []

    plan = installer.plan_for_file(
        brought, current="0.3.0", port=8080, on_progress=lines.append
    )

    assert plan.to_version == "0.3.1"
    assert plan.package == roots[0] / "hub_update" / brought.name
    assert plan.package.read_bytes() == b"brought"
    assert plan.package.stat().st_ino == brought.stat().st_ino
    assert plan.rollback is None
    assert lines[0] == "neutrino-hub_0.3.1_amd64.deb is in place"


def test_a_package_file_on_another_filesystem_is_copied_in(
    tmp_path, roots, monkeypatch
):
    brought = tmp_path / "neutrino-hub_0.3.1_amd64.deb"
    brought.write_bytes(b"brought")
    installer = make_installer(tmp_path, checker=Checker())

    def refuse_link(source, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(
        "neutrino_hub.modules.hub_update.installer.os.link", refuse_link
    )

    plan = installer.plan_for_file(brought, current="0.3.0", port=8080)

    assert plan.package.read_bytes() == b"brought"
    assert plan.package.stat().st_ino != brought.stat().st_ino


def test_the_same_version_brought_again_has_no_rollback_and_asks_no_release(
    tmp_path, roots
):
    brought = tmp_path / "neutrino-hub_0.3.0_amd64.deb"
    brought.write_bytes(b"same")
    checker = Checker()
    installer = make_installer(tmp_path, checker=checker)

    plan = installer.plan_for_file(brought, current="0.3.0", port=8080)

    assert plan.to_version == "0.3.0"
    assert plan.rollback is None
    assert checker.asked == []


def test_a_file_that_is_not_this_boxs_package_is_refused(tmp_path, roots):
    brought = tmp_path / "neutrino-agent_0.3.1_amd64.deb"
    brought.write_bytes(b"x")
    installer = make_installer(tmp_path, checker=Checker())

    with pytest.raises(ValueError):
        installer.plan_for_file(brought, current="0.3.0", port=8080)


# --- handing over ---


def plan_in(directory: Path, *, rollback: bool = True) -> HubUpdatePlan:
    return HubUpdatePlan(
        from_version="0.3.0",
        to_version="0.3.1",
        package=directory / "neutrino-hub_0.3.1_amd64.deb",
        rollback=directory / "neutrino-hub_0.3.0_amd64.deb" if rollback else None,
        family="debian",
        port=8080,
        units=("neutrino_hub_web",),
        started_at="2026-09-20T15:00:00Z",
    )


def test_launching_writes_the_script_and_the_record_and_starts_the_unit(
    tmp_path, roots
):
    launched = []
    installer = make_installer(tmp_path, checker=Checker(), launched=launched)
    directory = roots[0] / "hub_update"

    installer.launch(plan_in(directory))

    script = directory / "update.sh"
    assert script.stat().st_mode & 0o777 == 0o700
    assert script.read_text().startswith("#!/bin/sh")
    assert launched == [
        (
            [
                "systemd-run",
                "--unit",
                "neutrino_hub_update",
                "--collect",
                "--property=MemoryHigh=384M",
                "--setenv=DEBIAN_FRONTEND=noninteractive",
                "--setenv=DPKG_DEB_THREADS_MAX=1",
                "/bin/sh",
                str(script),
            ],
            {"timeout_s": 30},
        )
    ]
    record = installer._state.load()
    assert record.stage == "installing"
    assert record.from_version == "0.3.0"
    assert record.to_version == "0.3.1"
    assert record.started_at == "2026-09-20T15:00:00Z"


def test_a_unit_systemd_would_not_start_is_a_failed_record(tmp_path, roots):
    def refusing(command, **keywords):
        raise subprocess.CalledProcessError(1, command, stderr="Unit already exists")

    installer = make_installer(tmp_path, checker=Checker())
    installer._run = refusing

    with pytest.raises(HubUpdateError) as refused:
        installer.launch(plan_in(roots[0] / "hub_update"))

    assert refused.value.code == "update_launch_failed"
    record = installer._state.load()
    assert record.stage == "failed"
    assert record.reason == "update_launch_failed"
    assert record.finished_at.endswith("Z")


def test_the_unit_is_active_while_systemd_says_so(tmp_path, roots):
    assert make_installer(
        tmp_path, checker=Checker(), units={"neutrino_hub_update": "activating"}
    ).is_unit_active()
    assert not make_installer(tmp_path, checker=Checker()).is_unit_active()


# --- the script's text ---


def test_the_script_quotes_every_value_and_names_the_rollback(tmp_path):
    directory = tmp_path / "with space"
    plan = HubUpdatePlan(
        from_version="0.3.0",
        to_version="0.3.1",
        package=directory / "neutrino-hub_0.3.1_amd64.deb",
        rollback=directory / "neutrino-hub_0.3.0_amd64.deb",
        family="debian",
        port=8080,
        units=("neutrino_hub_web", "neutrino_hub_router"),
        started_at="2026-09-20T15:00:00Z",
    )

    text = render_script(plan, directory=directory, gate_timeout_s=7, poll_s=0.5)

    assert f"STATE='{directory}/state.json'" in text
    assert "UNITS='neutrino_hub_web neutrino_hub_router'" in text
    assert "GATE_TIMEOUT=7\n" in text
    assert "POLL=0.5\n" in text
    assert f"'{directory}/neutrino-hub_0.3.1_amd64.deb'" in text
    assert f"'{directory}/neutrino-hub_0.3.0_amd64.deb'" in text
    assert "/api/hub/display" in text


def test_a_plan_without_a_rollback_renders_an_empty_rollback(tmp_path):
    text = render_script(plan_in(tmp_path, rollback=False), directory=tmp_path)

    assert "ROLLBACK=''\n" in text
    assert "( false )" in text
