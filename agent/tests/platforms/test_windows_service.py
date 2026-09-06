"""The Windows service host: the handshake, with the manager faked.

A service process owes its manager three things — an entry it can dispatch,
a handler it can control, and a state it can read — and the agent owes them
without a wrapper binary. Every call rides the seam, so nothing here touches
a real service control manager.
"""

import threading

import pytest

from neutrino_agent.platforms import windows_service
from neutrino_agent.platforms.windows_service import (
    SERVICE_CONTROL_SHUTDOWN,
    SERVICE_CONTROL_STOP,
    SERVICE_PAUSED,
    SERVICE_RUNNING,
    SERVICE_START_PENDING,
    SERVICE_STOPPED,
    SERVICE_STOP_PENDING,
)

# What the manager hands back from a registration, and a control it sends
# that means neither stop nor shutdown.
STATUS_HANDLE = 4321
SERVICE_CONTROL_INTERROGATE = 4

# The marker the fake writes into its log where the control handler returned
# to it, which on a real manager is where ``ControlService`` completes.
HANDLER_RETURNED = "handler returned"


class FakeServiceApi:
    """The manager, scripted: it dispatches, then sends its controls."""

    def __init__(self, *, controls=(SERVICE_CONTROL_STOP,)):
        """
        Args:
            controls: What the manager sends once the service reads running.
        """
        self.dispatched = ""
        self.states: list = []
        self.handles: list = []
        self.started: list = []
        # Every state report and every return from the handler, in the order
        # they happened: what the manager's own control call is refused over
        # is an ordering, and only an ordering shows it.
        self.happened: list = []
        self.handler = None
        self._controls = controls
        self._running = threading.Event()

    def start_dispatcher(self, name: str, service_main) -> None:
        self.dispatched = name
        entry = threading.Thread(target=service_main, args=(1, None))
        entry.start()
        assert self._running.wait(timeout=5), "the service never reported running"
        for control in self._controls:
            self.handler(control)
            self.happened.append(HANDLER_RETURNED)
        entry.join(timeout=5)
        assert not entry.is_alive(), "the service entry never returned"

    def register_control_handler(self, name: str, handler):
        self.handler = handler
        return STATUS_HANDLE

    def set_status(self, handle, state: int) -> None:
        self.handles.append(handle)
        self.states.append(state)
        self.happened.append(state)
        if state == SERVICE_RUNNING:
            self._running.set()


class RefusingServiceApi:
    """A manager that will not be opened."""

    def query_state(self, name: str) -> int:
        raise OSError(5, "Access is denied")

    def start_service(self, name: str) -> None:
        raise OSError(1060, "The specified service does not exist")


def test_the_service_runs_the_loop_and_answers_the_manager():
    """START_PENDING, RUNNING, then the loop; a stop reports STOP_PENDING and
    STOPPED and returns, which is what ends the process."""
    api = FakeServiceApi()
    running = threading.Event()

    windows_service.host_service(name="NeutrinoAgent", run=running.set, api=api)

    assert api.dispatched == "NeutrinoAgent"
    assert api.states == [
        SERVICE_START_PENDING,
        SERVICE_RUNNING,
        SERVICE_STOP_PENDING,
        SERVICE_STOPPED,
    ]
    assert api.handles == [STATUS_HANDLE] * 4
    assert running.is_set()


def test_the_loop_runs_beside_the_entry_rather_than_inside_it():
    """The manager gets its running report while the agent beats: a loop that
    never returns must not be what the entry waits on."""
    api = FakeServiceApi()
    reported = []

    def run() -> None:
        reported.append(list(api.states))
        # A real loop never returns; this one outlives the entry the same way.
        threading.Event().wait(timeout=2)

    windows_service.host_service(name="NeutrinoAgent", run=run, api=api)

    assert reported == [[SERVICE_START_PENDING]]
    assert api.states[-1] == SERVICE_STOPPED


def test_the_handler_returns_before_the_stop_is_reported():
    """``sc stop`` answers 1061 on a stop that worked when STOPPED lands while
    the manager's own control call is still in flight. The handler's report is
    STOP_PENDING and nothing else; STOPPED comes after it has returned."""
    api = FakeServiceApi()

    windows_service.host_service(name="NeutrinoAgent", run=lambda: None, api=api)

    assert api.happened == [
        SERVICE_START_PENDING,
        SERVICE_RUNNING,
        SERVICE_STOP_PENDING,
        HANDLER_RETURNED,
        SERVICE_STOPPED,
    ]


def test_a_shutdown_stops_the_service_the_same_way():
    api = FakeServiceApi(controls=(SERVICE_CONTROL_SHUTDOWN,))

    windows_service.host_service(name="NeutrinoAgent", run=lambda: None, api=api)

    assert api.states[-2:] == [SERVICE_STOP_PENDING, SERVICE_STOPPED]


def test_a_control_that_is_not_a_stop_changes_nothing():
    api = FakeServiceApi(controls=(SERVICE_CONTROL_INTERROGATE, SERVICE_CONTROL_STOP))

    windows_service.host_service(name="NeutrinoAgent", run=lambda: None, api=api)

    assert api.states == [
        SERVICE_START_PENDING,
        SERVICE_RUNNING,
        SERVICE_STOP_PENDING,
        SERVICE_STOPPED,
    ]


@pytest.mark.parametrize(
    "state, word",
    [
        (SERVICE_RUNNING, "running"),
        (SERVICE_STOPPED, "stopped"),
        (SERVICE_START_PENDING, "starting"),
        (SERVICE_STOP_PENDING, "stopping"),
        (SERVICE_PAUSED, "paused"),
        (99, "unknown"),
    ],
)
def test_every_state_the_manager_holds_has_its_word(state, word):
    class Api:
        def query_state(self, name):
            return state

    assert windows_service.read_state("NeutrinoAgent", api=Api()) == word


def test_a_manager_that_refuses_reads_as_unknown():
    """Never installed, or not readable by this account: neither is a state,
    and neither may read as stopped."""
    assert (
        windows_service.read_state("NeutrinoAgent", api=RefusingServiceApi())
        == "unknown"
    )


def test_starting_asks_the_manager_by_name():
    asked = []

    class Api:
        def start_service(self, name):
            asked.append(name)

    windows_service.start("NeutrinoAgent", api=Api())

    assert asked == ["NeutrinoAgent"]


def test_a_start_the_manager_refuses_is_not_an_error():
    windows_service.start("NeutrinoAgent", api=RefusingServiceApi())
