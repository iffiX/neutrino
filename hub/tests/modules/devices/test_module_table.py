"""The description table: one frozen row per module, read by name and by kind.

What these pin: the rows come in the order the Modules page lists them and
every row's kind is one of the four; the programs run as an account are the
rows the shared router, panel and state composition are driven by, each
with its own sealed fields, published code and title; a row's file and
panel are named after the module unless the table says otherwise; and a
name the table does not hold is a ``KeyError``.
"""

import dataclasses

import pytest

from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
    DEVICE_MODULE_KIND_AGENT,
    DEVICE_MODULE_KIND_SERVICE_ACCOUNT,
    DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
    DEVICE_MODULE_KINDS,
    DEVICE_MODULE_PANEL_INSTANCES,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.module_table import (
    DEVICE_MODULE_ROWS,
    account_program_names,
    account_program_rows,
    module_row,
    rows_of_kind,
)


def test_the_rows_come_in_the_order_the_modules_page_lists_them():
    assert [row.name for row in DEVICE_MODULE_ROWS] == [
        "samba",
        "terminal",
        "remote_desktop",
        "gitea",
        "vscode",
        "code_server",
        "cloudcli",
        "podman",
        "zfs",
    ]


def test_every_shipped_manifest_has_a_row_and_every_row_a_manifest():
    assert {row.name for row in DEVICE_MODULE_ROWS} == set(load_module_manifests())


def test_every_row_is_one_of_the_four_kinds():
    kinds = {row.name: row.kind for row in DEVICE_MODULE_ROWS}

    assert set(kinds.values()) <= set(DEVICE_MODULE_KINDS)
    assert kinds == {
        "samba": DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
        "terminal": DEVICE_MODULE_KIND_AGENT,
        "remote_desktop": DEVICE_MODULE_KIND_AGENT,
        "gitea": DEVICE_MODULE_KIND_SERVICE_ACCOUNT,
        "vscode": DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        "code_server": DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        "cloudcli": DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        "podman": DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
        "zfs": DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
    }


def test_the_programs_run_as_an_account_are_three_rows_in_table_order():
    assert account_program_names() == ("vscode", "code_server", "cloudcli")
    assert [row.name for row in account_program_rows()] == list(account_program_names())
    assert rows_of_kind(DEVICE_MODULE_KIND_AGENT) == (
        module_row("terminal"),
        module_row("remote_desktop"),
    )


def test_each_program_run_as_an_account_seals_its_own_fields():
    """VS Code its token, code-server its secret, CloudCLI its password and
    its secret, each opened under the key the state carries."""
    sealed = {
        row.name: [(field.key, field.opened_key) for field in row.sealed_fields]
        for row in account_program_rows()
    }

    assert sealed == {
        "vscode": [("token_sealed", "token")],
        "code_server": [("secret_sealed", "secret")],
        "cloudcli": [
            ("web_password_sealed", "web_password"),
            ("token_secret_sealed", "token_secret"),
        ],
    }
    assert module_row("vscode").sealed_field("token_sealed").aad == (
        b"device_vscode:token"
    )
    assert module_row("vscode").sealed_field("token_sealed").secret_bytes == 24
    assert module_row("cloudcli").sealed_field("token_secret_sealed").secret_bytes == 32
    assert all(
        not row.sealed_fields
        for row in DEVICE_MODULE_ROWS
        if row.kind != DEVICE_MODULE_KIND_ACCOUNT_PROGRAM
    )


def test_each_program_run_as_an_account_names_its_token_and_its_login():
    """VS Code's server takes its token itself; the other two are opened with
    a token minted from the secret; code-server names no login."""
    rows = {row.name: row for row in account_program_rows()}

    assert (rows["vscode"].token_field, rows["vscode"].is_token_minted) == (
        "token_sealed",
        False,
    )
    assert (rows["code_server"].token_field, rows["code_server"].is_token_minted) == (
        "secret_sealed",
        True,
    )
    assert (rows["cloudcli"].token_field, rows["cloudcli"].is_token_minted) == (
        "token_secret_sealed",
        True,
    )
    assert {name: row.is_login_named for name, row in rows.items()} == {
        "vscode": True,
        "code_server": False,
        "cloudcli": True,
    }
    assert rows["vscode"].config_head == (("address", ""),)
    assert rows["code_server"].config_head == ()


def test_each_row_names_its_published_entry():
    published = {
        row.name: (row.description_code, row.entry_title) for row in DEVICE_MODULE_ROWS
    }

    assert published == {
        "samba": ("samba_module", ""),
        "terminal": ("", ""),
        "remote_desktop": ("", ""),
        "gitea": ("gitea_module", "Gitea"),
        "vscode": ("vscode_module", "VS Code ({account})"),
        "code_server": ("code_server_module", "code-server ({account})"),
        "cloudcli": ("cloudcli_module", "CloudCLI ({account})"),
        "podman": ("container", ""),
        "zfs": ("", ""),
    }


def test_each_row_names_its_file_its_panel_and_the_picker():
    for row in DEVICE_MODULE_ROWS:
        assert row.config_file == f"{row.name}.json", row.name
        if row.kind == DEVICE_MODULE_KIND_ACCOUNT_PROGRAM:
            assert row.panel == DEVICE_MODULE_PANEL_INSTANCES, row.name
        else:
            assert row.panel == row.name, row.name
        assert row.is_in_picker is (row.kind != DEVICE_MODULE_KIND_AGENT), row.name


def test_a_row_is_frozen_and_an_unknown_name_is_refused():
    with pytest.raises(dataclasses.FrozenInstanceError):
        module_row("samba").kind = "other"
    with pytest.raises(KeyError):
        module_row("anydesk")
    with pytest.raises(KeyError):
        module_row("samba").sealed_field("token_sealed")
    with pytest.raises(KeyError):
        module_row("vscode").sealed_field("secret_sealed")
