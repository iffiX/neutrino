#!/usr/bin/env python3
"""Drive the Windows lab VM through the QEMU guest agent on its host.

    vm.py exec "<command line>"          run one cmd.exe line as SYSTEM
    vm.py put <local> <C:\\path>          write one file into the VM
    vm.py user <C:\\script.ps1>           run a script as the signed-in person
    vm.py shot <name>                    screenshot the VM into <name>.png here
    vm.py serve                          serve ./share to the VM over the NAT bridge

The host, the domain and the share address come from the environment:
NEUTRINO_VM_HOST (user@host with virsh), NEUTRINO_VM_DOMAIN and
NEUTRINO_VM_SHARE_URL, with the lab's defaults below.
"""

import base64
import json
import os
import subprocess
import sys
import time

VM_HOST = os.environ.get("NEUTRINO_VM_HOST", "mlw0504@192.168.100.2")
VM_DOMAIN = os.environ.get("NEUTRINO_VM_DOMAIN", "win_interactive")
VM_SHARE_URL = os.environ.get("NEUTRINO_VM_SHARE_URL", "http://192.168.122.1:8000")
EXEC_TIMEOUT_S = 600.0
POLL_S = 2.0
CHUNK = 32768


def agent(payload: dict) -> dict:
    """One guest agent command, answered."""
    out = subprocess.run(
        [
            "ssh",
            VM_HOST,
            "virsh",
            "-c",
            "qemu:///system",
            "qemu-agent-command",
            VM_DOMAIN,
            json.dumps(json.dumps(payload)),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out.strip())["return"]


def run(path: str, args: list, timeout_s: float = EXEC_TIMEOUT_S) -> int:
    """Run one program in the guest, print its output, return its exit code."""
    pid = agent(
        {
            "execute": "guest-exec",
            "arguments": {"path": path, "arg": args, "capture-output": True},
        }
    )["pid"]
    deadline = time.time() + timeout_s
    while True:
        status = agent({"execute": "guest-exec-status", "arguments": {"pid": pid}})
        if status.get("exited"):
            break
        if time.time() > deadline:
            print("timeout", file=sys.stderr)
            return 124
        time.sleep(POLL_S)
    for key in ("out-data", "err-data"):
        if key in status:
            sys.stdout.write(base64.b64decode(status[key]).decode("utf-8", "replace"))
    return int(status.get("exitcode", 1))


def put(local: str, remote: str) -> None:
    """Write one local file into the guest."""
    data = open(local, "rb").read()
    handle = agent(
        {"execute": "guest-file-open", "arguments": {"path": remote, "mode": "wb"}}
    )
    for offset in range(0, len(data), CHUNK):
        chunk = base64.b64encode(data[offset : offset + CHUNK]).decode()
        agent(
            {
                "execute": "guest-file-write",
                "arguments": {"handle": handle, "buf-b64": chunk},
            }
        )
    agent({"execute": "guest-file-close", "arguments": {"handle": handle}})
    print(f"wrote {len(data)} bytes to {remote}")


def shot(name: str) -> None:
    """Screenshot the guest into <name>.png beside this script."""
    subprocess.run(
        [
            "ssh",
            VM_HOST,
            f"virsh -c qemu:///system screenshot {VM_DOMAIN} /tmp/shot.ppm >/dev/null "
            "&& convert /tmp/shot.ppm /tmp/shot.png",
        ],
        check=True,
    )
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".png")
    subprocess.run(["scp", "-q", f"{VM_HOST}:/tmp/shot.png", target], check=True)
    print(target)


def serve() -> None:
    """Serve ./share on the host to the guest over the NAT bridge."""
    bind = VM_SHARE_URL.split("//")[1].split(":")[0]
    port = VM_SHARE_URL.rsplit(":", 1)[1]
    subprocess.run(
        [
            "ssh",
            VM_HOST,
            f"mkdir -p ~/win_share && cd ~/win_share && (pgrep -f 'http.server {port}' "
            f">/dev/null || nohup python3 -m http.server {port} --bind {bind} "
            ">~/win_share.log 2>&1 &) && echo serving ~/win_share at {VM_SHARE_URL}",
        ],
        check=True,
    )


def main() -> int:
    verb, rest = sys.argv[1], sys.argv[2:]
    if verb == "exec":
        return run("cmd.exe", ["/c", rest[0]])
    if verb == "put":
        put(rest[0], rest[1])
        return 0
    if verb == "user":
        return run(
            "powershell.exe",
            [
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "C:\\user_run.ps1",
                rest[0],
            ],
        )
    if verb == "shot":
        shot(rest[0])
        return 0
    if verb == "serve":
        serve()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
