"""``nclient app``: list, open, stop and set against a scripted client.

``list`` groups the apps by machine, with each entry's kind and its fixed
local address before the app is used, ``/udp`` after a UDP one, and the
loopback host on macOS. An app is named by its name, its title, or
``<machine>/<app>`` where two machines hold one name. ``use`` posts
**Use**, waits for its job and prints the addresses or the failure;
``open`` posts **Open** and prints the page it opens; ``set``
takes ``<entry>=<port>`` and an empty port goes back to the hub's.
"""

import pytest

from neutrino_client.cli import app, wording


def test_list_groups_the_apps_by_machine_with_fixed_addresses(running, capsys):
    running.state["apps"][0]["is_in_use"] = True

    assert app.main_list() == 0

    out = capsys.readouterr().out.splitlines()
    assert out[:6] == [
        "lab-gpu (home)",
        "  gitea  module  in use",
        "    web  web  http://gitea.lab-gpu.localhost:25101/explore",
        "    ssh  port  127.0.0.1:26022",
        "  ssh  module  not in use",
        "    iffi  ssh  127.0.0.1:27001",
    ]
    assert "    port_53_udp  port  127.0.0.1:24053/udp" in out
    assert "build (office)" in out


def test_an_entry_with_no_number_is_listed_without_an_address(running, capsys):
    shell = next(
        entry
        for entry in running.state["services"]
        if entry["id"] == "ssh_server_d1_iffi"
    )
    shell["local_port"] = None

    assert app.main_list() == 0

    assert "    iffi  ssh" in capsys.readouterr().out.splitlines()


def test_list_of_one_hub_names_no_hub(running, capsys):
    assert app.main_list(hub="office") == 0

    out = capsys.readouterr().out.splitlines()
    assert out == [
        "build",
        "  gitea  module  not in use",
        "    web  web  https://gitea.build.localhost:25500/",
    ]


def test_an_unhealthy_entry_says_so_on_its_line(running, capsys):
    running.state["services"][0]["is_healthy"] = False

    assert app.main_list() == 0
    assert "(not reachable now)" in capsys.readouterr().out


def test_on_macos_every_address_is_the_loopback(running, capsys):
    running.state["platform"]["os"] = "darwin"

    assert app.main_list(hub="home") == 0
    assert "    web  web  http://127.0.0.1:25101/explore" in capsys.readouterr().out


def test_list_speaks_chinese(running, chinese, capsys):
    assert app.main_list(hub="office") == 0
    assert "  gitea  模块  未用" in capsys.readouterr().out


def test_use_posts_use_waits_and_prints_the_addresses(running, capsys):
    reads = []

    def using(state):
        reads.append(1)
        state["apps"][0]["job"] = "opening" if len(reads) < 3 else ""

    running.on_state = using

    assert app.main_use("lab-gpu/gitea") == 0

    assert running.posts("/api/app/use") == [{"hub_id": "h1", "app_id": "gitea_d1"}]
    assert running.posts("/api/app/open") == []
    assert capsys.readouterr().out.splitlines() == [
        "forwarding http://gitea.lab-gpu.localhost:25101/explore",
        "forwarding 127.0.0.1:26022",
    ]


def test_open_posts_open_and_prints_the_page_it_opens(running, capsys):
    running.state["apps"][0]["is_in_use"] = True

    assert app.main_open("lab-gpu/gitea") == 0

    assert running.posts("/api/app/open") == [{"hub_id": "h1", "app_id": "gitea_d1"}]
    assert capsys.readouterr().out.splitlines() == [
        "opening http://gitea.lab-gpu.localhost:25101/explore"
    ]


@pytest.mark.parametrize("code", ["app_not_in_use", "app_no_page"])
def test_open_refused_prints_the_code_and_exits_1(running, capsys, code):
    running.answers["/api/app/open"] = lambda body: (409, {"code": code, "params": {}})

    assert app.main_open("ssh") == 1
    assert capsys.readouterr().err.strip() == wording.word_code(code)


def test_two_machines_holding_one_name_are_asked_apart(running, capsys):
    assert app.main_use("gitea") == 1

    assert running.posts("/api/app/use") == []
    assert capsys.readouterr().err.strip() == (
        "gitea names more than one app; say which: build/gitea, lab-gpu/gitea"
    )


def test_hub_narrows_a_name_two_machines_hold(running):
    assert app.main_use("gitea", hub="office") == 0
    assert running.posts("/api/app/use") == [{"hub_id": "h2", "app_id": "gitea_d7"}]


def test_an_app_is_named_by_its_title_too(running):
    assert app.main_use("SSH") == 0
    assert running.posts("/api/app/use")[0]["app_id"] == "ssh_server_d1"


def test_a_name_that_matches_nothing_prints_the_apps(running, capsys):
    assert app.main_use("wiki") == 1

    err = capsys.readouterr().err.strip()
    assert err.startswith("no app named wiki; there are: ")
    assert "lab-gpu/gitea" in err and "home/dns" in err


def test_a_failed_use_prints_its_code_and_exits_1(running, capsys):
    running.state["apps"][0]["last_error"] = {
        "code": "port_taken",
        "params": {"port": 25101},
    }

    assert app.main_use("lab-gpu/gitea") == 1
    assert capsys.readouterr().err.strip() == wording.word_code(
        "port_taken", {"port": 25101}
    )


def test_a_use_refused_at_once_exits_1(running, capsys):
    running.answers["/api/app/use"] = lambda body: (
        403,
        {"code": "client_disabled", "params": {}},
    )

    assert app.main_use("ssh") == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_disabled")


def test_stop_posts_stop(running, capsys):
    assert app.main_stop("ssh") == 0

    assert running.posts("/api/app/stop") == [
        {"hub_id": "h1", "app_id": "ssh_server_d1"}
    ]
    assert capsys.readouterr().out.strip() == "stopped ssh"


def test_set_sends_each_entry_and_an_empty_one_as_the_hubs(running, capsys):
    assert app.main_set("lab-gpu/gitea", ["web=8080", "ssh="]) == 0

    assert running.posts("/api/app/set") == [
        {"hub_id": "h1", "app_id": "gitea_d1", "ports": {"web": 8080, "ssh": None}}
    ]


def test_set_of_an_entry_the_app_lacks_prints_its_entries(running, capsys):
    assert app.main_set("lab-gpu/gitea", ["http=8080"]) == 1

    assert running.posts("/api/app/set") == []
    assert capsys.readouterr().err.strip() == (
        "no entry named http; there are: web, ssh"
    )


@pytest.mark.parametrize("value", ["web", "web=eighty", "=8080"])
def test_set_of_a_port_of_the_wrong_shape_is_a_usage_error(running, capsys, value):
    assert app.main_set("lab-gpu/gitea", [value]) == 2
    assert running.posts("/api/app/set") == []


def test_set_with_no_port_is_a_usage_error(running):
    assert app.main_set("lab-gpu/gitea", []) == 2


def test_set_refused_prints_the_code(running, capsys):
    running.answers["/api/app/set"] = lambda body: (
        400,
        {"code": "port_taken", "params": {"port": 8080}},
    )

    assert app.main_set("lab-gpu/gitea", ["web=8080"]) == 1
    assert "8080" in capsys.readouterr().err


@pytest.mark.parametrize(
    "call",
    [
        lambda: app.main_list(),
        lambda: app.main_use("ssh"),
        lambda: app.main_open("ssh"),
        lambda: app.main_stop("ssh"),
        lambda: app.main_set("ssh", ["iffi=2222"]),
    ],
)
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


def test_an_unbound_client_lists_nothing_and_names_no_app(running, capsys):
    from tests.cli.conftest import unbound_document

    running.state = unbound_document()

    assert app.main_list() == 0
    assert capsys.readouterr().out == ""
    assert app.main_use("gitea") == 1
    assert capsys.readouterr().err.strip() == "no app named gitea; there are none"
