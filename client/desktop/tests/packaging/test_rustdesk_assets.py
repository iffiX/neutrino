"""The RustDesk pins, and where the Windows executable is staged; the
download is stood in for."""

import pytest

from shared import rustdesk_assets


def test_every_pin_is_a_flutter_asset_of_the_pinned_release():
    for (os_name, machine), (suffix, digest) in rustdesk_assets.RUSTDESK_ASSETS.items():
        url = rustdesk_assets.asset_url(os_name, machine)
        assert url.endswith(
            f"/{rustdesk_assets.RUSTDESK_VERSION}/rustdesk-1.4.9{suffix}"
        )
        assert "sciter" not in url
        assert len(digest) == 64
        assert digest == digest.lower()


def test_the_download_is_checked_against_its_pin(monkeypatch):
    asked = []

    def fetch(url, digest):
        asked.append((url, digest))
        return b"MZ"

    monkeypatch.setattr(rustdesk_assets, "_fetch", fetch)

    assert rustdesk_assets.download("windows", "x86_64") == b"MZ"
    assert asked == [
        (
            rustdesk_assets.asset_url("windows", "x86_64"),
            rustdesk_assets.RUSTDESK_ASSETS[("windows", "x86_64")][1],
        )
    ]


def test_the_windows_executable_takes_the_name_asked_for(monkeypatch, tmp_path):
    monkeypatch.setattr(rustdesk_assets, "_fetch", lambda url, digest: b"MZ")

    written = rustdesk_assets.stage_windows_exe(
        tmp_path / "bin", name="rustdesk-1.4.9-x86_64.exe"
    )

    assert written == tmp_path / "bin" / "rustdesk-1.4.9-x86_64.exe"
    assert written.read_bytes() == b"MZ"


def test_a_machine_with_no_pin_is_refused_by_name():
    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.asset_url("windows", "aarch64")

    assert "aarch64" in str(refused.value)
    assert "x86_64" in str(refused.value)


# --- the files upstream's Windows executable packs, for the agent ---


def _entry(path, content):
    import hashlib

    name = path.encode()
    return (
        len(name).to_bytes(4, "big")
        + name
        + len(content).to_bytes(4, "big")
        + content
        + hashlib.md5(content).hexdigest().encode()
    )


def _packer(*entries):
    """An executable as the portable packer writes it: code that names the
    identifier on its own, then the identifier and the packed files."""
    return b"MZ code rustdesk text " + b"rustdesk" + b"".join(entries) + b"tail"


@pytest.fixture
def identity(monkeypatch):
    """A decompressor that hands the bytes back as they are."""

    class Identity:
        @staticmethod
        def decompress(blob):
            return blob

    real = rustdesk_assets.importlib.import_module
    monkeypatch.setattr(
        rustdesk_assets.importlib,
        "import_module",
        lambda name: Identity if name == "brotli" else real(name),
    )


def test_the_packed_files_come_out_with_their_paths(identity):
    files = rustdesk_assets.packed_files(
        _packer(
            _entry(".\\rustdesk.exe", b"MZ host"),
            _entry(".\\data\\flutter_assets\\a.svg", b"<svg/>"),
        )
    )

    assert files == [
        (("rustdesk.exe",), b"MZ host"),
        (("data", "flutter_assets", "a.svg"), b"<svg/>"),
    ]


def test_a_packed_file_that_is_not_its_md5_stops_the_build(identity):
    entry = bytearray(_entry(".\\rustdesk.exe", b"MZ host"))
    entry[-1] = ord("0") if entry[-1] != ord("0") else ord("1")

    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.packed_files(_packer(bytes(entry)))

    assert "rustdesk.exe is not what its MD5 says" in str(refused.value)


def test_a_packed_path_that_climbs_out_stops_the_build(identity):
    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.packed_files(_packer(_entry(".\\..\\evil.dll", b"x")))

    assert "evil.dll" in str(refused.value)


def test_an_executable_with_nothing_packed_stops_the_build(identity):
    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.packed_files(b"MZ rustdesk nothing packed")

    assert str(refused.value) == "RustDesk's Windows executable carries no packed files"


def test_without_the_decompressor_the_build_says_what_to_install(monkeypatch):
    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(rustdesk_assets.importlib, "import_module", missing)

    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.packed_files(_packer(_entry(".\\rustdesk.exe", b"MZ")))

    assert str(refused.value).endswith("pip install brotli==1.2.0")


def test_the_agent_s_copy_is_laid_out_as_upstream_s_install_lays_it(
    tmp_path, monkeypatch, identity
):
    monkeypatch.setattr(
        rustdesk_assets,
        "download",
        lambda os_name, machine: _packer(
            _entry(".\\rustdesk.exe", b"MZ host"),
            _entry(".\\data\\app.so", b"so"),
        ),
    )

    written = rustdesk_assets.stage_windows_files(tmp_path / "rustdesk")

    assert sorted(path.relative_to(tmp_path).as_posix() for path in written) == [
        "rustdesk/data/app.so",
        "rustdesk/rustdesk.exe",
    ]
    assert (tmp_path / "rustdesk" / "rustdesk.exe").read_bytes() == b"MZ host"


def test_a_pack_without_the_program_stops_the_build(tmp_path, monkeypatch, identity):
    monkeypatch.setattr(
        rustdesk_assets,
        "download",
        lambda os_name, machine: _packer(_entry(".\\data\\app.so", b"so")),
    )

    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.stage_windows_files(tmp_path / "rustdesk")

    assert "packs no rustdesk.exe" in str(refused.value)
