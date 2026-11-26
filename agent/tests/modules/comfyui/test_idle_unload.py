"""Idle unload: an entry chosen once its time has passed with an empty queue, never while a prompt runs or waits, never twice for one entry and never for an empty history, and ``/free`` sent once and never under ``-1``."""

from neutrino_agent.modules.comfyui.idle_unload import ComfyuiIdleUnload, due_entry


def _history(prompt_id="p1", ended_ms=1_000_000):
    return {
        prompt_id: {
            "status": {
                "messages": [
                    ["execution_start", {"timestamp": ended_ms - 5000}],
                    ["execution_success", {"timestamp": ended_ms}],
                ]
            }
        }
    }


EMPTY = {"queue_running": [], "queue_pending": []}


def test_an_entry_idle_long_enough_with_an_empty_queue_is_due_once():
    history = _history(ended_ms=1_000_000)
    assert due_entry(EMPTY, history, now_s=1000 + 1800, idle_s=1800, freed="") == "p1"
    assert due_entry(EMPTY, history, now_s=1000 + 1799, idle_s=1800, freed="") == ""
    assert due_entry(EMPTY, history, now_s=9999, idle_s=1800, freed="p1") == ""
    assert due_entry(EMPTY, {}, now_s=9999, idle_s=1, freed="") == ""
    running = {"queue_running": [[0, "p2"]], "queue_pending": []}
    waiting = {"queue_running": [], "queue_pending": [[1, "p3"]]}
    assert due_entry(running, history, now_s=9999, idle_s=1, freed="") == ""
    assert due_entry(waiting, history, now_s=9999, idle_s=1, freed="") == ""
    assert due_entry(None, history, now_s=9999, idle_s=1, freed="") == ""


def test_the_unload_is_sent_once_and_never_under_never():
    calls = []
    answers = {"/queue": EMPTY, "/history?max_items=1": _history(ended_ms=1_000_000)}

    def call(port, path, body=None):
        calls.append((port, path, body))
        return answers.get(path, {})

    idle = ComfyuiIdleUnload(log=lambda line: None, call=call, clock=lambda: 5000)
    idle._port, idle._idle_s = 15000, 300
    assert idle.check_once() == "p1"
    assert calls[-1] == (
        15000,
        "/free",
        b'{"unload_models": true, "free_memory": true}',
    )
    assert idle.check_once() == ""
    assert [path for _port, path, _body in calls].count("/free") == 1
    idle._idle_s = None
    calls.clear()
    assert idle.check_once() == "" and calls == []
