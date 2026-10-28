"""The source sets: the one list of sources of each ecosystem, and the ones a state carries.

What these pin: the shipped file holds the three sets the standard writes,
each source an https address and the publisher's first; the loader refuses a
file outside the shape; a state carries each set its recipes name, by an
artifact's ``source_set`` or an entry's ``source_sets``, and no other; and a
placeholder names a set as ``{<set>}``.
"""

import json

import pytest

from neutrino_hub.modules.devices import source_sets as source_sets_module
from neutrino_hub.modules.devices.source_sets import (
    load_source_sets,
    placeholders_in,
    state_source_sets,
)


def test_the_shipped_file_holds_the_four_sets_of_the_standard():
    sets = load_source_sets()

    assert sets == {
        "pypi": {
            "probe": "/pip/",
            "sources": [
                "https://pypi.org/simple",
                "https://pypi.tuna.tsinghua.edu.cn/simple",
                "https://mirrors.aliyun.com/pypi/simple",
                "https://mirrors.cloud.tencent.com/pypi/simple",
            ],
            "variables": ["PIP_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX_URL"],
        },
        "npm": {
            "probe": "/npm/latest",
            "sources": [
                "https://registry.npmjs.org",
                "https://registry.npmmirror.com",
                "https://mirrors.cloud.tencent.com/npm",
            ],
            "variables": [
                "npm_config_registry",
                "YARN_NPM_REGISTRY_SERVER",
                "BUN_CONFIG_REGISTRY",
            ],
        },
        "huggingface": {
            "probe": "/openai-community/gpt2/resolve/main/config.json",
            "sources": ["https://huggingface.co", "https://hf-mirror.com"],
            "variables": ["HF_ENDPOINT"],
        },
        "ctan": {
            "probe": "/systems/texlive/tlnet/tlpkg/texlive.tlpdb.sha512",
            "sources": [
                "https://mirror.ctan.org",
                "https://mirrors.mit.edu/CTAN",
                "https://mirrors.tuna.tsinghua.edu.cn/CTAN",
                "https://mirrors.ustc.edu.cn/CTAN",
                "https://mirrors.aliyun.com/CTAN",
                "https://mirrors.cloud.tencent.com/CTAN",
                "https://mirrors.sjtug.sjtu.edu.cn/ctan",
                "https://mirror.nju.edu.cn/CTAN",
            ],
            "variables": [],
        },
    }


GOOD = {"probe": "/x", "sources": ["https://a.example"], "variables": ["X_URL"]}


@pytest.mark.parametrize(
    "held",
    [
        {},
        {"Py-Pi": GOOD},
        {"pypi": {**GOOD, "extra": 1}},
        {"pypi": {key: value for key, value in GOOD.items() if key != "probe"}},
        {"pypi": {**GOOD, "probe": "pip/"}},
        {"pypi": {**GOOD, "sources": []}},
        {"pypi": {**GOOD, "sources": ["http://a.example"]}},
        {"pypi": {**GOOD, "variables": "X_URL"}},
        {"pypi": {**GOOD, "variables": ["NOT A NAME"]}},
        [],
    ],
)
def test_the_loader_refuses_a_file_outside_the_shape(monkeypatch, tmp_path, held):
    path = tmp_path / "source_sets.json"
    path.write_text(json.dumps(held))
    monkeypatch.setattr(source_sets_module, "SOURCE_SETS_PATH", path)

    with pytest.raises(ValueError):
        load_source_sets()


def test_a_set_whose_tool_takes_its_source_on_its_command_line_names_no_variable(
    monkeypatch, tmp_path
):
    path = tmp_path / "source_sets.json"
    path.write_text(json.dumps({"ctan": {**GOOD, "variables": []}}))
    monkeypatch.setattr(source_sets_module, "SOURCE_SETS_PATH", path)

    assert load_source_sets() == {"ctan": {**GOOD, "variables": []}}


def test_the_loader_drops_the_comment_keys(monkeypatch, tmp_path):
    path = tmp_path / "source_sets.json"
    path.write_text(json.dumps({"_comment": "x", "pypi": {**GOOD, "_scan": "y"}}))
    monkeypatch.setattr(source_sets_module, "SOURCE_SETS_PATH", path)

    assert load_source_sets() == {"pypi": GOOD}


def test_a_state_carries_each_set_its_recipes_name_and_no_other():
    modules = {
        "cloudcli": {
            "install": {"params": {"artifacts": [{"kind": "npm", "source_set": "npm"}]}}
        },
        "demo": {"install": {"params": {"artifacts": [], "source_sets": ["pypi"]}}},
        "samba": {"install": {"params": {"packages": ["samba"]}}},
        "terminal": {"want": "running"},
    }

    carried = state_source_sets(modules)

    assert list(carried) == ["npm", "pypi"]
    assert carried["pypi"]["probe"] == "/pip/"
    assert state_source_sets({"samba": modules["samba"]}) == {}


def test_a_placeholder_names_a_set_in_braces():
    assert placeholders_in("INDEX={pypi}/simple") == ["pypi"]
    assert placeholders_in("A={npm}{huggingface}") == ["npm", "huggingface"]
    assert placeholders_in('JSON={"a": 1}') == []
