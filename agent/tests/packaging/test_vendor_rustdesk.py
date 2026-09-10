"""The RustDesk host the Linux packages carry, and what carrying it owes.

The pins are asserted as a table: every machine the agent is published for,
in both package formats, by a Flutter asset and never a sciter one. The
extraction is driven against packages built here, so what is pinned is the
judgment — the whole host directory carried, the upstream session files left
behind, a package with no host in it refused, and the licence beside it.
"""

import shutil
import subprocess

import pytest

import payload

UPSTREAM_FILES = (
    "usr/share/rustdesk/rustdesk",
    "usr/share/rustdesk/lib/librustdesk.so",
    "usr/share/rustdesk/data/flutter_assets/asset",
    "usr/share/rustdesk/files/README",
    "usr/bin/rustdesk",
    "usr/share/applications/rustdesk.desktop",
    "usr/share/polkit-1/actions/rustdesk.policy",
    "etc/rustdesk/startwm.sh",
    "etc/pam.d/rustdesk",
    "lib/systemd/system/rustdesk.service",
)


def _upstream_tree(root, files=UPSTREAM_FILES):
    """A tree shaped like the upstream package's payload.

    Args:
        root: Where to write it.
        files: The paths it holds.

    Returns:
        The root it was written under.
    """
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    return root


def _fixture_deb(tmp_path, files=UPSTREAM_FILES):
    """One .deb carrying an upstream-shaped payload.

    Args:
        tmp_path: The directory to build under.
        files: The paths the payload holds.

    Returns:
        The package's bytes.
    """
    tree = _upstream_tree(tmp_path / "deb_tree", files)
    control = tree / "DEBIAN/control"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(
        "Package: rustdesk\nVersion: 1.4.9\nArchitecture: amd64\n"
        "Maintainer: nobody <nobody@example.com>\nDescription: a fixture\n"
    )
    built = tmp_path / "rustdesk.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(built)],
        check=True,
        capture_output=True,
    )
    return built.read_bytes()


def _fixture_rpm(tmp_path):
    """One .rpm carrying an upstream-shaped payload.

    Args:
        tmp_path: The directory to build under.

    Returns:
        The package's bytes.
    """
    tree = _upstream_tree(tmp_path / "rpm_tree")
    spec = tmp_path / "rustdesk.spec"
    spec.write_text(
        "Name: rustdesk\nVersion: 1.4.9\nRelease: 0\nSummary: a fixture\n"
        "License: AGPL-3.0\nBuildArch: noarch\n"
        "%global __brp_mangle_shebangs %{nil}\n"
        "%description\na fixture\n"
        f"%install\nmkdir -p %{{buildroot}}\ncp -a {tree}/. %{{buildroot}}/\n"
        "%files\n" + "\n".join(f"/{name}" for name in UPSTREAM_FILES) + "\n"
    )
    subprocess.run(
        ["rpmbuild", "-bb", "--define", f"_topdir {tmp_path}", str(spec)],
        check=True,
        capture_output=True,
    )
    built = next((tmp_path / "RPMS").rglob("*.rpm"))
    return built.read_bytes()


@pytest.fixture
def downloaded(monkeypatch):
    """Whatever the test wants the pinned download to be.

    Returns:
        A callable that makes the fetch answer with those bytes.
    """

    def answering(raw):
        monkeypatch.setattr(payload, "fetch", lambda url, digest, what: raw)

    return answering


# --- the pins ---


def test_every_machine_the_agent_is_published_for_has_both_packages():
    machines = set(payload.DEBIAN_ARCHITECTURES) | set(payload.RPM_ARCHITECTURES)

    assert set(payload.RUSTDESK_ASSETS) == {
        (kind, machine) for kind in ("deb", "rpm") for machine in machines
    }


def test_the_pinned_assets_are_the_flutter_builds_and_carry_a_digest():
    for (kind, machine), (suffix, digest) in payload.RUSTDESK_ASSETS.items():
        assert "sciter" not in suffix
        assert suffix.endswith(f".{kind}")
        assert machine in suffix
        assert len(digest) == 64


def test_the_url_names_the_pinned_version_and_the_asset():
    url = payload.RUSTDESK_URL.format(
        version=payload.RUSTDESK_VERSION,
        suffix=payload.RUSTDESK_ASSETS[("deb", "x86_64")][0],
    )

    assert url.endswith("/1.4.9/rustdesk-1.4.9-x86_64.deb")


def test_a_machine_with_no_asset_is_refused_by_name(tmp_path):
    with pytest.raises(SystemExit) as refusal:
        payload.stage_rustdesk(tmp_path, "amd64", "msi")

    assert "no RustDesk msi pinned" in str(refusal.value)


# --- what is carried out of the package ---


def test_the_host_is_carried_under_usr_because_rustdesk_reads_its_own_prefix():
    """RustDesk 1.4.9's `is_installed()` is a prefix test on `current_exe`:
    anywhere but /usr it refuses `--password` and every seat password the hub
    hands down is rejected. It resolves symlinks first, so only the binary's
    own path answers this."""
    assert str(payload.RUSTDESK_VENDOR_DIR / payload.RUSTDESK_BINARY_NAME).startswith(
        "/usr/"
    )


def test_the_whole_host_directory_is_carried_and_nothing_around_it(
    tmp_path, downloaded
):
    downloaded(_fixture_deb(tmp_path))

    payload.stage_rustdesk(tmp_path / "tree", "amd64", "deb")

    vendor = tmp_path / "tree/usr/lib/neutrino_agent/rustdesk"
    assert (vendor / "rustdesk").is_file()
    assert (vendor / "lib/librustdesk.so").is_file()
    assert (vendor / "data/flutter_assets/asset").is_file()
    assert (vendor / "files/README").is_file()
    # Upstream's own session setup is not this package's to install.
    assert not (tmp_path / "tree/etc/rustdesk").exists()
    assert not (tmp_path / "tree/etc/pam.d").exists()
    assert not (tmp_path / "tree/usr/share/applications").exists()
    assert not (tmp_path / "tree/usr/share/polkit-1").exists()
    assert not (tmp_path / "tree/lib/systemd/system/rustdesk.service").exists()


def test_the_name_on_the_path_points_at_the_carried_binary(tmp_path, downloaded):
    downloaded(_fixture_deb(tmp_path))

    payload.stage_rustdesk(tmp_path / "tree", "amd64", "deb")

    link = tmp_path / "tree/usr/bin/rustdesk"
    assert link.is_symlink()
    assert str(link.readlink()) == "/usr/lib/neutrino_agent/rustdesk/rustdesk"


def test_a_package_carrying_no_host_fails_the_build(tmp_path, downloaded):
    """A silent miss would ship an agent whose desktop half is not there."""
    downloaded(
        _fixture_deb(tmp_path, files=("usr/share/applications/rustdesk.desktop",))
    )

    with pytest.raises(SystemExit) as refusal:
        payload.stage_rustdesk(tmp_path / "tree", "amd64", "deb")

    assert "usr/share/rustdesk/rustdesk" in str(refusal.value)


@pytest.mark.skipif(
    shutil.which("rpm2cpio") is None or shutil.which("rpmbuild") is None,
    reason="the rpm tooling is in the build container, not on every machine",
)
def test_the_rpm_is_opened_the_same_way_as_the_deb(tmp_path, downloaded):
    downloaded(_fixture_rpm(tmp_path))

    payload.stage_rustdesk(tmp_path / "tree", "x86_64", "rpm")

    vendor = tmp_path / "tree/usr/lib/neutrino_agent/rustdesk"
    assert (vendor / "rustdesk").is_file()
    assert (vendor / "lib/librustdesk.so").is_file()
    assert (tmp_path / "tree/usr/bin/rustdesk").is_symlink()


# --- the licence that carrying it owes ---


def test_the_licence_of_everything_carried_is_staged_beside_the_package(tmp_path):
    payload.stage_licenses(tmp_path)

    staged = tmp_path / "usr/share/doc/neutrino-agent/licenses"
    assert sorted(path.name for path in staged.iterdir()) == sorted(
        payload.CARRIED_LICENSES
    )
    carried = (staged / "rustdesk.txt").read_text()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in carried
    assert f"tree/{payload.RUSTDESK_VERSION}" in carried


def test_a_licence_that_did_not_reach_the_build_fails_it(tmp_path, monkeypatch):
    monkeypatch.setattr(payload, "REPO_ROOT", tmp_path / "nowhere")

    with pytest.raises(SystemExit) as refusal:
        payload.stage_licenses(tmp_path)

    assert "rustdesk.txt" in str(refusal.value)
