"""Replacing the databases the split runs on.

What these guard is the one failure that takes a gateway off the air: a
database written half-way, or written from bytes that are not what the
repository published. A digest that does not match leaves both files exactly
as they were, and a file that is replaced is replaced in one step.
"""

import hashlib
import json

import pytest

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.xray import geodata
from neutrino_hub.modules.xray.constants import (
    XRAY_GEODATA_DOWNLOAD_URL,
    XRAY_GEODATA_LATEST_URL,
    XRAY_GEODATA_SOURCE_PACKAGE,
    XRAY_GEODATA_SOURCE_RELEASE,
)
from tests.conftest import FakeSourceFetcher

GEOIP = "geoip.dat"
GEOSITE = "geosite.dat"
NEW = {GEOIP: "202609050329", GEOSITE: "20260914091725"}


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fake_release_fetcher(bodies: dict, sums: dict | None = None, *, latest=None):
    """A fetcher answering the repositories from a table, digests derived unless overridden.

    Args:
        bodies: Asset name to the bytes it answers with.
        sums: Asset name to the digest published beside it, where that
            should not be the digest of the bytes.
        latest: Repository to the answer its latest release gives; None
            names the tags of :data:`NEW`.

    Returns:
        A :class:`FakeSourceFetcher`.
    """
    table = {}
    for source in geodata.sources():
        tag = NEW[source.file_name]
        latest_url = XRAY_GEODATA_LATEST_URL.format(repository=source.repository)
        table[latest_url] = (
            json.dumps({"tag_name": tag}).encode("utf-8")
            if latest is None
            else latest[source.repository]
        )
        address = XRAY_GEODATA_DOWNLOAD_URL.format(
            repository=source.repository, release=tag, asset=source.asset
        )
        published = (sums or {}).get(source.asset, digest_of(bodies[source.asset]))
        table[address + ".sha256sum"] = f"{published}  {source.asset}\n".encode()
        table[address] = bodies[source.asset]
    return FakeSourceFetcher(table)


@pytest.fixture
def bodies():
    return {
        source.asset: f"{source.file_name} payload".encode("utf-8")
        for source in geodata.sources()
    }


@pytest.fixture
def directory(tmp_path):
    """A geodata directory holding the databases the package carries."""
    directory = tmp_path / "geodata"
    directory.mkdir()
    for name in (GEOIP, GEOSITE):
        (directory / name).write_bytes(b"carried by the package")
    return directory


def test_every_pin_names_a_repository_and_an_asset():
    """The pins are the only place the two repositories are written down, so a
    pin that stopped being a release address would leave the panel with
    nothing to ask."""
    sources = {source.file_name: source for source in geodata.sources()}

    assert sources[GEOIP].repository == "v2fly/geoip"
    assert sources[GEOIP].asset == "geoip-only-cn-private.dat"
    assert sources[GEOSITE].repository == "v2fly/domain-list-community"
    assert sources[GEOSITE].asset == "dlc.dat"
    assert all(source.release for source in sources.values())


def test_a_machine_that_has_taken_nothing_reads_as_the_package(tmp_path):
    state = geodata.installed(version_path=tmp_path / "version.json")

    assert state == geodata.baseline()
    assert state.source == XRAY_GEODATA_SOURCE_PACKAGE


@pytest.mark.parametrize(
    "recorded",
    ["not json at all", json.dumps({"releases": {GEOIP: "202609050329"}})],
)
def test_a_version_file_that_says_nothing_useful_reads_as_the_package(
    tmp_path, recorded
):
    """Half a record is not a state: the file names both databases or it is
    the package's own copies that are on the disk."""
    path = tmp_path / "version.json"
    path.write_text(recorded, encoding="utf-8")

    assert geodata.installed(version_path=path) == geodata.baseline()


def test_the_version_file_is_what_a_fetch_wrote(tmp_path, directory, bodies):
    version_path = tmp_path / "version.json"

    written = geodata.fetch(
        NEW,
        directory=directory,
        version_path=version_path,
        fetcher=fake_release_fetcher(bodies),
    )

    read_back = geodata.installed(version_path=version_path)
    assert written.releases == NEW
    assert read_back.releases == NEW
    assert read_back.source == XRAY_GEODATA_SOURCE_RELEASE


def test_the_newest_release_is_read_off_each_repository(bodies):
    fetcher = fake_release_fetcher(bodies)

    assert geodata.latest(fetcher=fetcher) == NEW
    assert [kind for kind, _, _ in fetcher.asked] == ["document", "document"]


def test_a_repository_that_names_no_release_is_refused(bodies):
    fetcher = fake_release_fetcher(
        bodies,
        latest={
            "v2fly/geoip": b"{}",
            "v2fly/domain-list-community": b"{}",
        },
    )

    with pytest.raises(DownloadFailedError) as raised:
        geodata.latest(fetcher=fetcher)

    assert raised.value.params["sources"][0]["reason"] == "digest_mismatch"


def test_a_file_that_is_not_what_was_published_replaces_nothing(
    tmp_path, directory, bodies
):
    """The second database is the one that fails, so this also asserts the
    first one is not written before both have been checked."""
    version_path = tmp_path / "version.json"
    fetcher = fake_release_fetcher(bodies, sums={"dlc.dat": "0" * 64})

    with pytest.raises(DownloadFailedError):
        geodata.fetch(
            NEW,
            directory=directory,
            version_path=version_path,
            fetcher=fetcher,
        )

    assert (directory / GEOIP).read_bytes() == b"carried by the package"
    assert (directory / GEOSITE).read_bytes() == b"carried by the package"
    assert not version_path.exists()


def test_a_digest_file_that_holds_no_digest_replaces_nothing(
    tmp_path, directory, bodies
):
    fetcher = fake_release_fetcher(bodies, sums={"dlc.dat": "not a digest"})

    with pytest.raises(DownloadFailedError):
        geodata.fetch(
            NEW,
            directory=directory,
            version_path=tmp_path / "version.json",
            fetcher=fetcher,
        )

    assert (directory / GEOSITE).read_bytes() == b"carried by the package"
    assert sorted(path.name for path in directory.iterdir()) == [GEOIP, GEOSITE]


def test_each_database_is_replaced_in_one_step(
    tmp_path, directory, bodies, monkeypatch
):
    """xray reads these files while the machine runs, so a database is never
    on the disk as a partial write: it arrives beside itself and is moved
    over."""
    replaced = []
    real_replace = geodata.os.replace

    def note(source, target):
        replaced.append((str(source), str(target)))
        real_replace(source, target)

    monkeypatch.setattr(geodata.os, "replace", note)

    geodata.fetch(
        NEW,
        directory=directory,
        version_path=tmp_path / "version.json",
        fetcher=fake_release_fetcher(bodies),
    )

    assert sorted(target for _, target in replaced) == sorted(
        [
            str(directory / GEOIP),
            str(directory / GEOSITE),
            str(tmp_path / "version.json"),
        ]
    )
    assert all(staged != target for staged, target in replaced)
    assert (directory / GEOIP).read_bytes() == bodies["geoip-only-cn-private.dat"]
    assert (directory / GEOSITE).read_bytes() == bodies["dlc.dat"]
    assert not list(directory.glob(".tmp_*"))
    assert not list(directory.glob(".partial_*"))


def test_a_release_missing_for_a_database_is_refused(tmp_path, directory, bodies):
    with pytest.raises(KeyError):
        geodata.fetch(
            {GEOIP: NEW[GEOIP]},
            directory=directory,
            version_path=tmp_path / "version.json",
            fetcher=fake_release_fetcher(bodies),
        )
