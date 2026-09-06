"""What the shipped RustDesk manifest promises.

Every artifact is pinned by an exact URL and a checksum this hub took
itself, because upstream publishes none; every asset is a Flutter build,
because the sciter ones carry a proprietary engine the AGPL does not admit;
and the AGPL block names the license and the exact tag its corresponding
source is at, which is what the About panel credits and what the cache
fetches beside the binary.
"""

import re

from neutrino_hub.modules.devices.agent_module_cache import resolve_platform_entry
from neutrino_hub.modules.devices.manifests import load_module_manifests

PINNED_VERSION = "1.4.9"

# Every platform the module offers, and the asset each must resolve to.
EXPECTED_ASSETS = {
    "linux-debian-amd64": ("rustdesk-1.4.9-x86_64.deb", "deb"),
    "linux-debian-arm64": ("rustdesk-1.4.9-aarch64.deb", "deb"),
    "linux-rhel-amd64": ("rustdesk-1.4.9-0.x86_64.rpm", "rpm"),
    "windows-amd64": ("rustdesk-1.4.9-x86_64.msi", "msi"),
    "windows-arm64": ("rustdesk-1.4.9-aarch64.msi", "msi"),
    "darwin-amd64": ("rustdesk-1.4.9-x86_64.dmg", "dmg"),
    "darwin-arm64": ("rustdesk-1.4.9-aarch64.dmg", "dmg"),
}

# The checksums this hub took of the 1.4.9 assets, in the order the assets
# are declared above. A vendor re-cutting a release under the same tag
# changes these, and the cache refuses rather than installing whatever
# turned up. Each is a published checksum of a public download, not a
# credential.
EXPECTED_DIGEST_ORDER = (
    "7244ba47c40e804172044bfbe659467c54ce46554c98e78c8c0406f1d612fda3",  # scan: allow
    "ce62c996f14d33f3bbe3a330e953644a44bace7f05885a7953f7395d69fb49c0",  # scan: allow
    "eb1b053ac5b2f774f2271f7fbbfd2ea475899f7a55135c5e172bc54b9388f108",  # scan: allow
    "c87d2f4cef2a5acd6003b6507dcfbf5d5168a256db082cd90b54d35193224aaa",  # scan: allow
    "30bc8925e62c7ade52371758c2b944036ed2386f6c554e9e59f3bcfef06c7cd9",  # scan: allow
    "fa1129a0635019f9c5841937942cc2b08be028a192f47c009edde7e53812904e",  # scan: allow
    "f7935597b247d42c8f2a2ed71176a9f5868018cd9e1a33b8096418a668c8caf0",  # scan: allow
)
EXPECTED_DIGESTS = dict(zip(EXPECTED_ASSETS, EXPECTED_DIGEST_ORDER))

PLATFORM_TUPLES = {
    "linux-debian-amd64": {"os": "linux", "family": "debian", "arch": "amd64"},
    "linux-debian-arm64": {"os": "linux", "family": "debian", "arch": "arm64"},
    "linux-rhel-amd64": {"os": "linux", "family": "rhel", "arch": "amd64"},
    "windows-amd64": {"os": "windows", "family": "", "arch": "amd64"},
    "windows-arm64": {"os": "windows", "family": "", "arch": "arm64"},
    "darwin-amd64": {"os": "darwin", "family": "", "arch": "amd64"},
    "darwin-arm64": {"os": "darwin", "family": "", "arch": "arm64"},
}

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def manifest() -> dict:
    return load_module_manifests()["rustdesk"]


def test_the_module_is_hub_tier_and_named_by_its_own_kind():
    shipped = manifest()

    assert shipped["installer"] == "hub"
    assert shipped["kind"] == "rustdesk"
    assert shipped["title"] == "RustDesk"
    assert shipped["version"] == PINNED_VERSION


def test_every_platform_pins_its_own_asset_by_url():
    platforms = manifest()["platforms"]

    assert set(platforms) == set(EXPECTED_ASSETS)
    for key, (asset, package_kind) in EXPECTED_ASSETS.items():
        assert platforms[key]["url"].endswith(f"/{PINNED_VERSION}/{asset}")
        assert platforms[key]["package_kind"] == package_kind


def test_every_platform_pins_this_hubs_own_sha256():
    platforms = manifest()["platforms"]

    for key, digest in EXPECTED_DIGESTS.items():
        assert SHA256_PATTERN.match(platforms[key]["sha256"]), key
        assert platforms[key]["sha256"] == digest


def test_no_asset_is_ever_a_sciter_build():
    # The sciter builds carry a proprietary engine, so no platform may name
    # one however the file happens to be spelled.
    for entry in manifest()["platforms"].values():
        assert "sciter" not in entry["url"]


def test_the_agpl_block_names_the_license_and_the_exact_tag():
    shipped = manifest()

    assert shipped["license"] == "AGPL-3.0"
    assert shipped["corresponding_source"].endswith(f"/tree/{PINNED_VERSION}")
    assert shipped["source_archive"].endswith(f"/tags/{PINNED_VERSION}.tar.gz")


def test_every_platform_carries_a_verify_and_an_uninstall():
    for key, entry in manifest()["platforms"].items():
        assert entry["verify"], key
        assert entry["uninstall"], key


def test_each_platform_tuple_resolves_to_its_own_entry():
    shipped = manifest()

    for key, platform in PLATFORM_TUPLES.items():
        resolved_key, entry = resolve_platform_entry(shipped, platform)
        assert resolved_key == key
        assert entry["url"].endswith(EXPECTED_ASSETS[key][0])


def test_a_platform_with_no_build_resolves_to_nothing():
    # 32-bit ARM is dropped, and the manifest offers it nothing rather than
    # handing it a build for another machine.
    _, entry = resolve_platform_entry(
        manifest(), {"os": "linux", "family": "debian", "arch": "armv7"}
    )

    assert entry is None


def test_the_pins_and_the_assets_are_one_table():
    # The digests are ordered against the assets above, so a platform added
    # to one and not the other must fail rather than silently go unpinned.
    assert len(EXPECTED_DIGEST_ORDER) == len(EXPECTED_ASSETS)
    assert len(set(EXPECTED_DIGEST_ORDER)) == len(EXPECTED_ASSETS)
