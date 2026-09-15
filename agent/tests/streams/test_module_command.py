"""The command stream: a module, a verb, its arguments, and its close.

What these pin: the open's ``module`` and ``verb`` reach the runner with
the rest of the open as the verb's arguments, each line the command prints
goes up as one binary frame, the close carries the exit status, the
output and the result, a refusal closes with its code, and a stream the
hub closed takes no more lines.
"""

from neutrino_agent.streams.module_command import ModuleCommandStream
from tests.streams.fake_channel import FakeChannel


def recording_run(calls, **outcome):
    def run(module, verb, args, on_line):
        calls.append((module, verb, args))
        if on_line is not None:
            on_line("line one")
            on_line("line two")
        return {"exit_code": 0, "code": "", "params": {}, "output": "ran", **outcome}

    return run


def served(channel, args, run) -> dict:
    stream = ModuleCommandStream(channel, args, run=run)
    stream.open()
    return stream.run()


def test_the_verb_reaches_the_runner_with_the_rest_of_the_open_as_its_args():
    calls: list = []
    channel = FakeChannel()

    closed = served(
        channel,
        {"module": "samba", "verb": "set_password", "name": "ann", "password": "x"},
        recording_run(calls),
    )

    assert calls == [("samba", "set_password", {"name": "ann", "password": "x"})]
    assert channel.sent == [b"line one\n", b"line two\n"]
    assert closed == {
        "code": "",
        "params": {"exit_code": 0, "output": "ran", "result": {}},
    }


def test_a_reading_verb_closes_with_its_result():
    closed = served(
        FakeChannel(),
        {"module": "agent", "verb": "remote_desktop_read", "product": "anydesk"},
        recording_run([], result={"is_installed": True}),
    )

    assert closed["params"]["result"] == {"is_installed": True}


def test_a_refusal_closes_with_its_code_and_params():
    def refuse(module, verb, args, on_line):
        return {
            "exit_code": 1,
            "code": "verb_unknown",
            "params": {"module": module, "verb": verb},
            "output": "",
        }

    closed = served(FakeChannel(), {"module": "samba", "verb": "reticulate"}, refuse)

    assert closed == {
        "code": "verb_unknown",
        "params": {
            "module": "samba",
            "verb": "reticulate",
            "exit_code": 1,
            "output": "",
            "result": {},
        },
    }


def test_a_stream_the_hub_closed_takes_no_more_lines():
    channel = FakeChannel()

    def run(module, verb, args, on_line):
        on_line("before")
        channel.is_closed = True
        on_line("after")
        return {"exit_code": 0, "code": "", "params": {}, "output": ""}

    closed = served(channel, {"module": "podman", "verb": "journal"}, run)

    assert channel.sent == [b"before\n"]
    assert closed["params"]["exit_code"] == 0


def test_an_open_missing_its_module_or_verb_reaches_the_runner_as_empty():
    calls: list = []

    served(FakeChannel(), {}, recording_run(calls))

    assert calls == [("", "", {})]
