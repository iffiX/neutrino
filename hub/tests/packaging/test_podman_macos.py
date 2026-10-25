"""The parts of ``packaging/ci/podman_macos.py`` that run before the runner's root step.

The check itself installs Podman on a macOS runner; what is asserted here is
what feeds it: the cache key made of the entry's pinned digests, and the
fetch that downloads each missing artifact from its first source, keeps a
cached one and refuses a file whose digest is not its pin.
"""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "ci" / "podman_macos.py"
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "neutrino_hub"
    / "data"
    / "manifests"
    / "podman.json"
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("ci_podman_macos", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def branch(platform_name: str) -> dict:
    return json.loads(MANIFEST.read_text())["platforms"][platform_name]


@pytest.mark.parametrize("platform_name", ["darwin-arm64", "darwin-amd64"])
def test_the_cache_key_names_the_entrys_pkg_and_image_digests(script, platform_name):
    pins = {
        item["name"]: item["digest"].removeprefix("sha256:")
        for item in branch(platform_name)["install"]["params"]["artifacts"]
    }

    assert script.cache_key(platform_name) == (
        f"podman_{platform_name}_{pins['podman']}_{pins['image']}"
    )


def pinned_to(monkeypatch, script, contents: dict) -> list:
    """The manifest's darwin-arm64 entry pinned to these bytes per name."""
    artifacts = [
        {
            "name": name,
            "kind": "pkg" if name == "podman" else "raw_zst",
            "file": f"{name}-{{version}}",
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "sources": ["https://example.invalid/{file}"],
        }
        for name, data in contents.items()
    ]
    fetched = []

    def branch_of(platform_name):
        return {"install": {"params": {"version": "1", "artifacts": artifacts}}}

    def urlopen(url):
        fetched.append(url)
        name = url.rsplit("/")[-1].removesuffix("-1")
        return io.BytesIO(b"tampered" if "bad" in url else contents[name])

    monkeypatch.setattr(script, "_branch", branch_of)
    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    return fetched


def test_fetch_downloads_each_missing_file_under_the_agents_name(
    script, monkeypatch, tmp_path
):
    fetched = pinned_to(
        monkeypatch, script, {"podman": b"pkg bytes", "image": b"zstd bytes"}
    )

    script.fetch("darwin-arm64", tmp_path)

    assert (tmp_path / "installer.pkg").read_bytes() == b"pkg bytes"
    assert (tmp_path / "image.raw.zst").read_bytes() == b"zstd bytes"
    assert fetched == [
        "https://example.invalid/podman-1",
        "https://example.invalid/image-1",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "image.raw.zst",
        "installer.pkg",
    ]


def test_fetch_keeps_a_cached_file_whose_digest_is_its_pin(
    script, monkeypatch, tmp_path
):
    fetched = pinned_to(
        monkeypatch, script, {"podman": b"pkg bytes", "image": b"zstd bytes"}
    )
    (tmp_path / "installer.pkg").write_bytes(b"pkg bytes")
    (tmp_path / "image.raw.zst").write_bytes(b"an older image")

    script.fetch("darwin-arm64", tmp_path)

    assert fetched == ["https://example.invalid/image-1"]
    assert (tmp_path / "image.raw.zst").read_bytes() == b"zstd bytes"


def test_fetch_refuses_a_file_whose_digest_is_not_its_pin(
    script, monkeypatch, tmp_path
):
    pinned_to(monkeypatch, script, {"bad": b"pkg bytes"})

    with pytest.raises(SystemExit) as refused:
        script.fetch("darwin-arm64", tmp_path)

    assert "https://example.invalid/bad-1" in str(refused.value)
    assert list(tmp_path.iterdir()) == []
