"""The first run served by the hub's service, and the lock it shares with
``nhub setup``.

The wizard's server, the steps and the panel are fakes. What is pinned is
that the service serves the wizard behind the kept token, runs the steps
when the browser answers, exits with the restart status once the box is set
up, keeps serving after answers it cannot use or a run that failed, and that
whichever process starts the steps first holds the lock the other is
refused by.
"""

import json
import threading

import pytest

from neutrino_hub.cli import setup
from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.system.constants import SYSTEM_RESTART_EXIT_STATUS
from neutrino_hub.web.setup_app import SetupLock

ANSWERS = {"password": "x", "network": {"mode": "server"}}


class FakeServer:
    """The wizard's server: takes the port, and posts each answers document
    the test lines up as the browser would."""

    instances: list = []

    def __init__(self, *, session, host, port):
        self.session = session
        self.host = host
        self.port = port
        self.is_listening = True
        self.is_stopped = False
        self.documents: list = []
        FakeServer.instances.append(self)

    def start(self) -> bool:
        return self.is_listening

    def stop(self) -> None:
        self.is_stopped = True


class Stop(threading.Event):
    """A stop asked after the service has looked at it a number of times."""

    def __init__(self, after: int):
        super().__init__()
        self.after = after

    def is_set(self) -> bool:
        self.after -= 1
        return self.after < 0


@pytest.fixture
def service(monkeypatch):
    """The service's first run, with the server, the questions and the steps
    stood in for."""
    FakeServer.instances = []
    state = {"is_set_up": False, "runs": [], "statuses": [], "documents": []}
    monkeypatch.setattr(setup, "WebSetupServer", FakeServer)
    monkeypatch.setattr(setup, "ensure_setup_token", lambda: "kept-token")
    monkeypatch.setattr(setup, "_browser_port", lambda: 8080)
    monkeypatch.setattr(setup.wizard, "context", lambda: {"modes": []})
    monkeypatch.setattr(setup, "_skipped_steps", lambda: ())
    monkeypatch.setattr(setup, "is_password_set", lambda: state["is_set_up"])

    def from_document(document):
        if document.get("password") == "":
            raise setup.WizardAborted("a password is needed")
        return document

    monkeypatch.setattr(setup.wizard, "from_document", from_document)

    def run_steps(reporter, steps, answers, *, server, is_service):
        state["runs"].append((answers, server, is_service))
        return state["statuses"].pop(0)

    monkeypatch.setattr(setup, "_setup", run_steps)
    original_wait = setup.WebSetupSession.wait

    def wait(session, timeout_s):
        if state["documents"]:
            session.answer(state["documents"].pop(0))
        return original_wait(session, 0)

    monkeypatch.setattr(setup.WebSetupSession, "wait", wait)
    return state


def test_answers_run_the_steps_and_the_service_exits_into_the_panel(service):
    service["documents"] = [ANSWERS]
    service["statuses"] = [SYSTEM_RESTART_EXIT_STATUS]

    assert setup.serve_until_set_up(Stop(after=5)) == SYSTEM_RESTART_EXIT_STATUS

    (server,) = FakeServer.instances
    assert (server.host, server.port) == ("0.0.0.0", 8080)
    assert server.session.token == "kept-token"
    ((answers, run_server, is_service),) = service["runs"]
    assert answers == ANSWERS
    assert run_server is server
    assert is_service


def test_answers_it_cannot_use_go_back_and_the_lock_is_let_go(service):
    service["documents"] = [{"password": ""}]

    assert setup.serve_until_set_up(Stop(after=3)) == 0

    (server,) = FakeServer.instances
    assert service["runs"] == []
    assert server.session.state()["state"] == "rejected"
    assert server.is_stopped
    assert setup.SETUP_LOCK._descriptor is None


def test_a_run_that_failed_keeps_the_wizard_and_takes_the_next_answers(service):
    service["documents"] = [ANSWERS, ANSWERS]
    service["statuses"] = [1, SYSTEM_RESTART_EXIT_STATUS]

    assert setup.serve_until_set_up(Stop(after=10)) == SYSTEM_RESTART_EXIT_STATUS

    assert len(service["runs"]) == 2


def test_a_box_set_up_from_the_terminal_ends_the_wizard(service):
    service["is_set_up"] = True

    assert setup.serve_until_set_up(Stop(after=5)) == SYSTEM_RESTART_EXIT_STATUS

    assert FakeServer.instances[0].is_stopped
    assert service["runs"] == []


def test_a_box_set_up_while_the_terminal_still_holds_the_lock_keeps_waiting(
    service, setup_files
):
    service["is_set_up"] = True
    terminal = SetupLock(path=setup_files / "setup.lock", platform=HubPlatform())
    assert terminal.acquire()

    assert setup.serve_until_set_up(Stop(after=2)) == 0

    terminal.release()


def test_a_port_it_cannot_take_is_a_failure(service, monkeypatch):
    monkeypatch.setattr(FakeServer, "start", lambda self: False)

    assert setup.serve_until_set_up(Stop(after=5)) == 1


def test_the_terminal_is_refused_while_another_process_runs_the_steps(
    setup_files, capsys
):
    other = SetupLock(path=setup_files / "setup.lock", platform=HubPlatform())
    assert other.acquire()

    assert setup._setup(None, [], None) == 1

    assert '"code": "setup_in_progress"' in capsys.readouterr().err
    other.release()


class _Session:
    def __init__(self):
        self.finished: list = []

    def finish(self, **keywords):
        self.finished.append(keywords)

    def wait_done_served(self, timeout_s):
        return True


class _Server:
    def __init__(self):
        self.session = _Session()
        self.is_stopped = False

    def stop(self):
        self.is_stopped = True


def test_the_service_hands_over_by_exiting_and_leaves_the_agent_to_the_panel(
    monkeypatch, setup_files
):
    server = _Server()
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(setup.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        setup, "_start_panel", lambda reporter: pytest.fail("the service is the panel")
    )
    monkeypatch.setattr(
        setup,
        "_install_local_agent",
        lambda *a, **k: pytest.fail("the panel installs the agent"),
    )

    status = setup._hand_over(
        server, "http://192.0.2.7:8080", "pw", None, is_service=True
    )

    assert status == SYSTEM_RESTART_EXIT_STATUS
    assert server.is_stopped
    assert server.session.finished == [
        {"panel_url": "http://192.0.2.7:8080", "authority": None}
    ]
    assert (setup_files / "setup_local_agent").is_file()


def test_the_panel_installs_the_agent_the_first_run_left_to_it(
    monkeypatch, setup_files
):
    mark = setup_files / "setup_local_agent"
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.touch()
    installed = []
    monkeypatch.setattr(setup, "_wait_for_panel", lambda: None)
    monkeypatch.setattr(
        setup,
        "_install_local_agent",
        lambda password, reporter, *, link_of: installed.append(link_of),
    )
    monkeypatch.setattr(setup, "UTILS_SETUP_LOG_PATH", setup_files / "setup.log")

    setup.finish_local_agent()

    assert installed == [setup._minted_link]
    assert not mark.exists()


def test_with_no_mark_the_panel_installs_nothing(monkeypatch):
    monkeypatch.setattr(
        setup, "_install_local_agent", lambda *a, **k: pytest.fail("nothing to do")
    )

    setup.finish_local_agent()


def test_a_terminal_beside_the_serving_service_points_at_it_and_asks_here(
    monkeypatch, capsys
):
    welcomed = []
    monkeypatch.setattr(setup, "_is_service_serving", lambda: True)
    monkeypatch.setattr(setup, "ensure_setup_token", lambda: "kept-token")
    monkeypatch.setattr(setup, "_browser_port", lambda: 8080)
    monkeypatch.setattr(
        setup, "_reachable_urls", lambda port: [f"http://192.0.2.7:{port}"]
    )
    monkeypatch.setattr(setup.wizard, "welcome", lambda: welcomed.append(True))
    monkeypatch.setattr(
        setup, "_browser_server", lambda session: pytest.fail("one wizard is enough")
    )

    assert setup._browser_answers() is None

    assert "http://192.0.2.7:8080/?token=kept-token" in capsys.readouterr().out
    assert welcomed == [True]


# --- the hub's own agent after a restore ---


@pytest.fixture
def rejoining(monkeypatch, setup_files):
    """A restore's mark in place, the panel answering, and every join recorded."""
    joins: list = []
    minted: list = []
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(setup, "_wait_for_panel", lambda: None)
    monkeypatch.setattr(setup, "UTILS_SETUP_LOG_PATH", setup_files / "setup.log")
    monkeypatch.setattr(setup, "is_local_agent_installed", lambda: True)
    monkeypatch.setattr(
        setup,
        "_minted_link",
        lambda device_id=None: minted.append(device_id) or ("neutrino://enroll/x", ""),
    )
    monkeypatch.setattr(setup, "run", lambda command, **kwargs: joins.append(command))
    mark = setup_files / "restore_local_agent"
    mark.parent.mkdir(parents=True, exist_ok=True)
    return mark, minted, joins


def test_after_a_restore_the_agent_joins_the_row_the_restore_named(rejoining):
    mark, minted, joins = rejoining
    mark.write_text(json.dumps({"device_id": "dev-hub"}))

    setup.rejoin_local_agent()

    assert minted == ["dev-hub"]
    assert joins == [
        [
            setup.hub_platform().agent_command(),
            "join",
            "neutrino://enroll/x",
            "--yes",
        ]
    ]
    assert not mark.exists()


def test_after_a_restore_naming_no_row_the_agent_joins_by_its_machine(rejoining):
    mark, minted, joins = rejoining
    mark.write_text(json.dumps({"device_id": ""}))

    setup.rejoin_local_agent()

    assert minted == [None]
    assert len(joins) == 1
    assert not mark.exists()


def test_a_machine_without_its_agent_joins_nothing_after_a_restore(
    rejoining, monkeypatch
):
    mark, minted, joins = rejoining
    mark.write_text(json.dumps({"device_id": "dev-hub"}))
    monkeypatch.setattr(setup, "is_local_agent_installed", lambda: False)

    setup.rejoin_local_agent()

    assert (minted, joins) == ([], [])
    assert not mark.exists()


def test_with_no_restore_mark_nothing_joins(rejoining):
    _mark, minted, joins = rejoining

    setup.rejoin_local_agent()

    assert (minted, joins) == ([], [])
