"""The parts of ``packaging/ci/podman_macos.py`` that run before the runner's root step.

The check itself installs Podman on a macOS runner; what is asserted here is
what feeds it: the cache key made of the branch's pinned digests, and the
fetch that downloads each missing file, keeps a cached one and refuses a
file whose digest is not its pin.
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
def test_the_cache_key_names_the_branchs_pkg_and_image_digests(script, platform_name):
    pins = {
        item["name"]: item["sha256"] for item in branch(platform_name)["components"]
    }

    assert script.cache_key(platform_name) == (
        f"podman_{platform_name}_{pins['installer']}_{pins['image']}"
    )


def pinned_to(monkeypatch, script, contents: dict) -> list:
    """The manifest's darwin-arm64 branch pinned to these bytes per name."""
    components = [
        {
            "name": name,
            "url": f"https://example.invalid/{name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "package_kind": "pkg" if name == "installer" else "raw_zst",
        }
        for name, data in contents.items()
    ]
    fetched = []

    def branch_of(platform_name):
        return {"components": components}

    def urlopen(url):
        fetched.append(url)
        return io.BytesIO(
            b"tampered" if "bad" in url else contents[url.rsplit("/")[-1]]
        )

    monkeypatch.setattr(script, "_branch", branch_of)
    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    return fetched


def test_fetch_downloads_each_missing_file_under_the_agents_name(
    script, monkeypatch, tmp_path
):
    fetched = pinned_to(
        monkeypatch, script, {"installer": b"pkg bytes", "image": b"zstd bytes"}
    )

    script.fetch("darwin-arm64", tmp_path)

    assert (tmp_path / "installer.pkg").read_bytes() == b"pkg bytes"
    assert (tmp_path / "image.raw.zst").read_bytes() == b"zstd bytes"
    assert fetched == [
        "https://example.invalid/installer",
        "https://example.invalid/image",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "image.raw.zst",
        "installer.pkg",
    ]


def test_fetch_keeps_a_cached_file_whose_digest_is_its_pin(
    script, monkeypatch, tmp_path
):
    fetched = pinned_to(
        monkeypatch, script, {"installer": b"pkg bytes", "image": b"zstd bytes"}
    )
    (tmp_path / "installer.pkg").write_bytes(b"pkg bytes")
    (tmp_path / "image.raw.zst").write_bytes(b"an older image")

    script.fetch("darwin-arm64", tmp_path)

    assert fetched == ["https://example.invalid/image"]
    assert (tmp_path / "image.raw.zst").read_bytes() == b"zstd bytes"


def test_fetch_refuses_a_file_whose_digest_is_not_its_pin(
    script, monkeypatch, tmp_path
):
    pinned_to(monkeypatch, script, {"bad": b"pkg bytes"})

    with pytest.raises(SystemExit) as refused:
        script.fetch("darwin-arm64", tmp_path)

    assert "https://example.invalid/bad" in str(refused.value)
    assert list(tmp_path.iterdir()) == []
