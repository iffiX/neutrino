"""The service dispatcher against a fake advapi32.

The fake plays the service control manager: its dispatcher call runs the
service's main through the real function pointer in the table, records
every status reported, and hands the control handler to the test. The
stdcall function types are swapped for the C ones Linux has, so the
pointers are real ones.
"""

import ctypes
import threading
import time

import pytest

from neutrino_hub.platforms import win32, windows_service
from neutrino_hub.platforms.windows_service import ServiceControlDispatcher

MAIN_TYPE = ctypes.CFUNCTYPE(None, win32.DWORD, ctypes.c_void_p)
HANDLER_TYPE = ctypes.CFUNCTYPE(
    win32.DWORD, win32.DWORD, win32.DWORD, ctypes.c_void_p, ctypes.c_void_p
)


@pytest.fixture(autouse=True)
def _c_function_types(monkeypatch):
    monkeypatch.setattr(win32, "service_main_type", lambda: MAIN_TYPE)
    monkeypatch.setattr(win32, "service_handler_type", lambda: HANDLER_TYPE)


class FakeAdvapi32:
    """The service control manager, as far as one service sees it."""

    def __init__(self, *, is_from_manager=True):
        self.is_from_manager = is_from_manager
        self.names = []
        self.states = []
        self.accepted = []
        self.handler = None
        self.registered = threading.Event()

    def StartServiceCtrlDispatcherW(self, table):
        if not self.is_from_manager:
            return 0
        self.names.append(table[0].lpServiceName)
        main = ctypes.cast(table[0].lpServiceProc, MAIN_TYPE)
        main(0, None)
        return 1

    def RegisterServiceCtrlHandlerExW(self, name, handler, context):
        self.handler = ctypes.cast(handler, HANDLER_TYPE)
        self.registered.set()
        return 77

    def SetServiceStatus(self, handle, status):
        assert handle == 77
        self.states.append(status._obj.dwCurrentState)
        self.accepted.append(status._obj.dwControlsAccepted)
        return 1


class Exits:
    """os._exit, recorded instead of taken."""

    def __init__(self):
        self.statuses = []
        self.happened = threading.Event()

    def __call__(self, status):
        self.statuses.append(status)
        self.happened.set()


def dispatch_in_thread(dispatcher):
    thread = threading.Thread(target=dispatcher.run, daemon=True)
    thread.start()
    return thread


def wait_for(condition, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("never happened")


def test_the_service_starts_pending_then_runs_the_hub():
    advapi32 = FakeAdvapi32()
    started = threading.Event()
    exits = Exits()
    dispatcher = ServiceControlDispatcher(
        "neutrino_hub",
        on_start=lambda: started.wait(),
        on_stop=lambda: None,
        advapi32=advapi32,
        exit=exits,
    )

    dispatch_in_thread(dispatcher)
    wait_for(lambda: win32.SERVICE_RUNNING in advapi32.states)

    assert advapi32.names == ["neutrino_hub"]
    assert advapi32.states[:2] == [win32.SERVICE_START_PENDING, win32.SERVICE_RUNNING]
    assert advapi32.accepted[1] == (
        win32.SERVICE_ACCEPT_STOP | win32.SERVICE_ACCEPT_SHUTDOWN
    )
    started.set()


@pytest.mark.parametrize(
    "control", [win32.SERVICE_CONTROL_STOP, win32.SERVICE_CONTROL_SHUTDOWN]
)
def test_a_stop_runs_on_stop_then_reports_stopped_and_ends(control):
    advapi32 = FakeAdvapi32()
    order = []
    exits = Exits()
    holding = threading.Event()
    dispatcher = ServiceControlDispatcher(
        "neutrino_hub",
        on_start=holding.wait,
        on_stop=lambda: order.append(("on_stop", list(advapi32.states))),
        advapi32=advapi32,
        exit=exits,
    )
    thread = dispatch_in_thread(dispatcher)
    wait_for(lambda: win32.SERVICE_RUNNING in advapi32.states)

    assert advapi32.handler(control, 0, None, None) == win32.NO_ERROR
    thread.join(timeout=5)

    assert order == [
        (
            "on_stop",
            [
                win32.SERVICE_START_PENDING,
                win32.SERVICE_RUNNING,
                win32.SERVICE_STOP_PENDING,
            ],
        )
    ]
    assert advapi32.states[-1] == win32.SERVICE_STOPPED
    assert exits.statuses == [0]
    assert not thread.is_alive()
    holding.set()


def test_a_hub_that_ends_by_itself_ends_the_process_as_a_crash():
    advapi32 = FakeAdvapi32()
    exits = Exits()
    dispatcher = ServiceControlDispatcher(
        "neutrino_hub",
        on_start=lambda: None,
        on_stop=lambda: None,
        advapi32=advapi32,
        exit=exits,
    )

    dispatch_in_thread(dispatcher)
    exits.happened.wait(timeout=5)

    assert exits.statuses == [1]
    assert win32.SERVICE_STOPPED not in advapi32.states


def test_interrogate_is_answered_and_an_unknown_control_is_not_implemented():
    advapi32 = FakeAdvapi32()
    holding = threading.Event()
    dispatcher = ServiceControlDispatcher(
        "neutrino_hub",
        on_start=holding.wait,
        on_stop=lambda: None,
        advapi32=advapi32,
        exit=Exits(),
    )
    dispatch_in_thread(dispatcher)
    advapi32.registered.wait(timeout=5)

    assert (
        advapi32.handler(win32.SERVICE_CONTROL_INTERROGATE, 0, None, None)
        == win32.NO_ERROR
    )
    assert advapi32.handler(0x0000000A, 0, None, None) == (
        win32.ERROR_CALL_NOT_IMPLEMENTED
    )
    holding.set()


def test_a_process_the_manager_did_not_start_is_refused(monkeypatch):
    monkeypatch.setattr(windows_service.win32, "last_error", lambda: OSError(1063))
    dispatcher = ServiceControlDispatcher(
        "neutrino_hub",
        on_start=lambda: None,
        on_stop=lambda: None,
        advapi32=FakeAdvapi32(is_from_manager=False),
        exit=Exits(),
    )

    with pytest.raises(OSError):
        dispatcher.run()
