"""The folder shares of ``samba.json``, read and changed as pure functions."""

import pytest

from neutrino_hub.modules.devices.folder_shares import (
    folder_shares,
    in_file_share_order,
    is_share_name_valid,
    with_accounts_only,
    with_folder_share,
    without_folder_share,
)


@pytest.mark.parametrize(
    "name, is_valid",
    [
        ("lab", True),
        ("Lab.data-2_x", True),
        ("x" * 64, True),
        ("x" * 65, False),
        ("", False),
        ("two words", False),
        ("GLOBAL", False),
        ("homes", False),
        ("Printers", False),
        ("lab/../etc", False),
    ],
)
def test_a_name_is_letters_digits_and_three_marks_outside_smb_confs_sections(
    name, is_valid
):
    assert is_share_name_valid(name) is is_valid


def test_a_share_replaced_keeps_its_place_and_a_record_of_another_shape_is_dropped():
    stored = {
        "accounts": [{"account": "ann"}],
        "shares": [
            {"name": "a", "path": "/a", "accounts": ["ann"]},
            "stray",
            {"name": "b", "path": "/b", "accounts": []},
        ],
    }

    replaced = with_folder_share(stored, {"name": "a", "path": "/a2", "accounts": []})
    removed = without_folder_share(replaced, "a")

    assert folder_shares(replaced) == [
        {"name": "a", "path": "/a2", "accounts": []},
        {"name": "b", "path": "/b", "accounts": []},
    ]
    assert folder_shares(removed) == [{"name": "b", "path": "/b", "accounts": []}]
    assert removed["accounts"] == [{"account": "ann"}]


def test_narrowing_to_the_enabled_accounts_keeps_every_share_in_their_order():
    stored = {"shares": [{"name": "a", "path": "/a", "accounts": ["bob", "ann"]}]}

    assert with_accounts_only(stored, ["ann", "carol"])["shares"] == [
        {"name": "a", "path": "/a", "accounts": ["ann"]}
    ]
    assert with_accounts_only({"accounts": []}, ["ann"]) == {"accounts": []}
    assert in_file_share_order(["bob", "ann", "eve"], ["ann", "bob"]) == [
        "ann",
        "bob",
    ]
