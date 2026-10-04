"""Reading `config/` and writing a real file from its example.

An example's records are placeholders: the real file a step writes from one
carries the shape and none of them, and a placeholder id left in a real file
by an older setup never reaches a library.
"""

import json

from neutrino_hub.utils import json_file
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR


def test_a_real_file_from_an_example_carries_no_placeholder_record(tmp_path):
    real = tmp_path / "clients" / "clients.json"

    json_file.copy_example(
        UTILS_EXAMPLES_DIR / "clients" / "clients.example.json", real
    )

    text = real.read_text(encoding="utf-8")
    written = json.loads(text)
    assert "_example_" not in text
    assert written["clients"] == {}
    assert written["default_permission"]["devices"] == {"terminal": []}
    assert "terminal" in written["default_permission"]["kinds"]
    assert "_comment" in written
    assert real.stat().st_mode & 0o777 == 0o600


def test_every_example_seeds_a_file_without_placeholders(tmp_path):
    for example in UTILS_EXAMPLES_DIR.rglob("*.example.json"):
        real = tmp_path / example.relative_to(UTILS_EXAMPLES_DIR)

        json_file.copy_example(example, real)

        assert "_example_" not in real.read_text(encoding="utf-8"), example


def test_a_placeholder_id_already_in_a_real_file_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(json_file, "UTILS_CONFIG_DIR", tmp_path)
    (tmp_path / "clients").mkdir()
    (tmp_path / "clients" / "clients.json").write_text(
        json.dumps(
            {
                "default_permission": {
                    "kinds": ["terminal"],
                    "devices": {
                        "terminal": ["_example_7d2e9f1a0b3c4d5e6f708192a3b4c5d6", "d1"]
                    },
                },
                "clients": {},
            }
        ),
        encoding="utf-8",
    )

    read = json_file.read_config("clients/clients.json")

    assert read["default_permission"]["devices"]["terminal"] == ["d1"]
