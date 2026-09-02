"""The agent channel's port rides the panel's settings file.

One field beside ``listen_port``: the example carries it, a written value is
read back, and a settings file from before the field existed falls back to
the default rather than failing to serve.
"""

import json

from neutrino_hub.cli import run
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT


def settings_file(tmp_path, monkeypatch, content: dict):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    path = tmp_path / "web" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def test_a_written_port_is_read_back(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"agent_listen_port": 9443})

    assert run._configured_agent_port() == 9443


def test_a_settings_file_without_the_field_gets_the_default(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"listen_port": 8080})

    assert run._configured_agent_port() == WEB_DEFAULT_AGENT_LISTEN_PORT


def test_the_example_carries_the_field():
    example = json.loads(
        (UTILS_EXAMPLES_DIR / "web" / "settings.example.json").read_text(
            encoding="utf-8"
        )
    )

    assert example["agent_listen_port"] == WEB_DEFAULT_AGENT_LISTEN_PORT
