"""A stand-in for the PowerShell host: the same line protocol, scripted by each request.

    python fake_powershell_host.py <log file>

Each request's ``args["mode"]`` says how it is answered: ``value`` (the
default) answers ``args["value"]``; ``refuse`` a refusal with ``code`` and
``params``; ``error`` an error with ``message``; ``sleep`` waits
``seconds`` first; ``crash`` ends the process unanswered; ``wrong_id``
answers another request's id; ``noise`` writes a line that is no JSON
first; ``bom`` puts a byte order mark before the answer. Every answer
reports ``args["private_bytes"]``, 1000 when unnamed. The log gets a line
when the process starts, when a request begins and ends, and at the end of
standard input.
"""

import json
import os
import sys
import time


def note(log: str, text: str) -> None:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(text + "\n")


def answer_to(request: dict) -> dict:
    args = request.get("args") or {}
    mode = args.get("mode", "value")
    answer = {"id": request.get("id"), "private_bytes": args.get("private_bytes", 1000)}
    if mode == "refuse":
        answer.update(
            ok=False, kind="refusal", code=args["code"], params=args["params"]
        )
    elif mode == "error":
        answer.update(ok=False, kind="error", message=args["message"])
    else:
        answer.update(ok=True, value=args.get("value"))
    if mode == "wrong_id":
        answer["id"] = request.get("id", 0) + 100
    return answer


def main() -> None:
    log = sys.argv[1]
    note(log, f"start {os.getpid()}")
    while True:
        line = sys.stdin.readline()
        if not line:
            note(log, "eof")
            return
        request = json.loads(line)
        args = request.get("args") or {}
        mode = args.get("mode", "value")
        note(log, f"begin {request['id']} {request['op']}")
        if mode == "crash":
            os._exit(3)
        if mode == "sleep":
            time.sleep(args["seconds"])
        if mode == "noise":
            sys.stdout.write("WARNING: a stray line\n")
        text = json.dumps(answer_to(request))
        if mode == "bom":
            text = "\ufeff" + text
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        note(log, f"end {request['id']}")


main()
