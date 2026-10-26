"""How a person names things: the slug rule, local names, shares and ssh hosts."""

import pytest

from neutrino_client.cli import names
from tests.cli.conftest import state_document


@pytest.mark.parametrize(
    "text, slugged",
    [
        ("Lab GPU", "lab-gpu"),
        ("code-server (alice)", "code-server-alice"),
        ("--x--", "x"),
        ("", "machine"),
        ("a" * 80, "a" * 63),
    ],
)
def test_the_slug_rule_is_the_local_names(text, slugged):
    assert names.slug(text) == slugged


def test_an_apps_name_and_machine_come_from_its_local_name():
    app = {"local_name": "code-server-alice.lab-gpu.localhost", "title": "x"}

    assert names.app_name(app) == "code-server-alice"
    assert names.app_machine(app) == "lab-gpu"


def test_an_app_with_no_local_name_takes_its_titles_slug():
    assert names.app_name({"title": "My Wiki"}) == "my-wiki"


def test_a_machine_with_several_shares_needs_the_share_named(capsys):
    state = state_document()
    second = dict(state["services"][7], id="share_d1_lab")
    second["payload"] = dict(second["payload"], share="lab")
    state["services"].append(second)

    assert names.choose_share(state, "lab-gpu") is None
    assert "lab-gpu/alice, lab-gpu/lab" in capsys.readouterr().err
    assert names.choose_share(state, "lab-gpu/lab")["id"] == "share_d1_lab"


def test_a_share_is_named_by_its_machines_slug_too():
    state = state_document()

    assert names.choose_share(state, "192-168-1-9/media")["id"] == "nas_file_media"


def test_ssh_hosts_list_the_accounts_in_the_hubs_order():
    [host] = names.ssh_hosts(state_document())

    assert host["host"] == "lab-gpu"
    assert host["accounts"] == ["iffi", "lab"]
    assert [entry["id"] for entry in host["entries"]] == [
        "ssh_server_d1_iffi",
        "ssh_server_d1_lab",
    ]


@pytest.mark.parametrize("needle", ["lab-gpu", "lab-gpu.nt", "d1", "iffi@lab-gpu.nt"])
def test_an_ssh_machine_is_named_with_or_without_nt(needle):
    machine, entry = names.choose_ssh(state_document(), needle)

    assert machine["host"] == "lab-gpu"
    assert entry["id"] == "ssh_server_d1_iffi"
