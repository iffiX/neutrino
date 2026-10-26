"""The declared apps' store: what it keeps, what it refuses, and the 0.5 records.

What these pin: an app is ``{id, name, host, description, created_at,
entries}`` under ``apps``; a 0.5 record of the kind ``http``, ``generic_tcp``
or ``generic_udp`` reads as an app of one entry with the record's id, a
``samba`` record as an app with one ``file`` entry per share, and each is
written into ``apps`` at the next write; a declaration is refused
``declared_service_invalid {field}`` naming ``name``, ``host``, ``entries``
(no entry, or two entries of one name) or ``entries.<n>.<field>``; and a ``file`` entry left without a port gets
445.
"""

import json

import pytest

from neutrino_hub.exceptions import ServiceFieldInvalidError
from neutrino_hub.modules.services.config import DeclaredAppRegistry
from neutrino_hub.modules.services.constants import SERVICES_DECLARED_PATH
from neutrino_hub.utils.json_file import write_config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def stored(config_dir) -> dict:
    return json.loads((config_dir / SERVICES_DECLARED_PATH).read_text())


def test_an_app_is_stored_with_its_entries_and_read_back(config_dir):
    registry = DeclaredAppRegistry()

    app = registry.add(
        name="NAS",
        host="192.168.100.50",
        entries=[
            {"type": "web", "port": 443, "scheme": "https", "path": "/"},
            {"type": "port", "port": 53, "protocol": "udp"},
            {"type": "file", "share": "media"},
        ],
        description="the NAS",
    )

    assert app.name == "NAS" and app.description == "the NAS"
    assert [(entry.type, entry.port, entry.name) for entry in app.entries] == [
        ("web", 443, "web_443"),
        ("port", 53, "port_53_udp"),
        ("file", 445, "file_media"),
    ]
    assert [held.id for held in DeclaredAppRegistry().list_apps()] == [app.id]
    assert DeclaredAppRegistry().get(app.id).host == "192.168.100.50"
    assert set(stored(config_dir)["apps"][0]) == {
        "id",
        "name",
        "host",
        "description",
        "created_at",
        "entries",
    }


def test_a_0_5_record_reads_as_an_app_of_one_entry_and_is_rewritten(config_dir):
    write_config(
        SERVICES_DECLARED_PATH,
        {
            "services": [
                {
                    "id": "rec1",
                    "name": "Printer",
                    "kind": "http",
                    "host": "192.168.100.9",
                    "port": 80,
                    "scheme": "http",
                    "path": "/",
                    "description": "",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "rec2",
                    "name": "Game",
                    "kind": "generic_udp",
                    "host": "192.168.100.9",
                    "port": 27015,
                },
                {
                    "id": "rec3",
                    "name": "NAS",
                    "kind": "samba",
                    "host": "192.168.100.50",
                    "port": 445,
                    "shares": [{"name": "media"}, {"name": "photos"}],
                },
            ]
        },
    )

    apps = {app.id: app for app in DeclaredAppRegistry().list_apps()}

    assert set(apps) == {"rec1", "rec2", "rec3"}
    assert [(entry.type, entry.name) for entry in apps["rec1"].entries] == [
        ("web", "web_80")
    ]
    assert [(entry.type, entry.name) for entry in apps["rec2"].entries] == [
        ("port", "port_27015_udp")
    ]
    assert [(entry.type, entry.share) for entry in apps["rec3"].entries] == [
        ("file", "media"),
        ("file", "photos"),
    ]
    DeclaredAppRegistry().delete("rec2")
    written = stored(config_dir)
    assert {app["id"] for app in written["apps"]} == {"rec1", "rec3"}
    assert "services" not in written or written["services"] == []


@pytest.mark.parametrize(
    "fields, field",
    [
        ({"name": " ", "host": "h", "entries": [{"type": "web", "port": 80}]}, "name"),
        ({"name": "a", "host": "", "entries": [{"type": "web", "port": 80}]}, "host"),
        ({"name": "a", "host": "h", "entries": []}, "entries"),
        (
            {"name": "a", "host": "h", "entries": [{"type": "rdp", "port": 1}]},
            "entries.0.type",
        ),
        ({"name": "a", "host": "h", "entries": [{"type": "web"}]}, "entries.0.port"),
        (
            {
                "name": "a",
                "host": "h",
                "entries": [{"type": "web", "port": 80, "scheme": "ftp"}],
            },
            "entries.0.scheme",
        ),
        (
            {
                "name": "a",
                "host": "h",
                "entries": [{"type": "port", "port": 1, "protocol": "x"}],
            },
            "entries.0.protocol",
        ),
        ({"name": "a", "host": "h", "entries": [{"type": "file"}]}, "entries.0.share"),
        (
            {
                "name": "a",
                "host": "h",
                "entries": [{"type": "port", "port": 1}, {"type": "port", "port": 1}],
            },
            "entries",
        ),
        (
            {
                "name": "a",
                "host": "h",
                "entries": [
                    {"type": "file", "share": "a b"},
                    {"type": "file", "share": "A-B"},
                ],
            },
            "entries",
        ),
    ],
)
def test_a_declaration_is_refused_by_the_field_that_is_wrong(config_dir, fields, field):
    with pytest.raises(ServiceFieldInvalidError) as refused:
        DeclaredAppRegistry().add(description="", **fields)

    assert refused.value.code == "declared_service_invalid"
    assert refused.value.params == {"field": field}
    assert not (config_dir / SERVICES_DECLARED_PATH).exists()


def test_deleting_an_unknown_app_is_a_key_error(config_dir):
    with pytest.raises(KeyError):
        DeclaredAppRegistry().delete("nothing")
