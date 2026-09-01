"""Run a command inside a lab VM without touching its network.

    vm_exec.py <domain> <shell command>
    vm_exec.py <domain> push <local file> <path in guest>

The channel is the QEMU guest agent, which reaches the guest over virtio-serial
through the hypervisor. That matters here: what these VMs exist to test is a
hub that reconfigures networking, and a command channel that goes down with
the thing under test is no channel at all.

Exits with the guest command's own status.
"""

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

URI = "qemu:///system"
POLL_INTERVAL_S = 0.4
POLL_LIMIT_S = 1800


def agent(domain: str, command: dict) -> dict:
    """Send one command to a domain's guest agent.

    Args:
        domain: The libvirt domain name.
        command: The agent command, as its JSON structure.

    Returns:
        The agent's ``return`` object.

    Raises:
        SystemExit: If virsh fails or the agent does not answer.
    """
    result = subprocess.run(
        ["virsh", "-c", URI, "qemu-agent-command", domain, json.dumps(command)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"{domain}: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout).get("return", {})


def run(domain: str, script: str) -> int:
    """Run a shell command in the guest and print what it wrote.

    Args:
        domain: The libvirt domain name.
        script: The shell command line.

    Returns:
        The command's exit status.

    Raises:
        SystemExit: If the command outlives the poll limit.
    """
    started = agent(
        domain,
        {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/sh",
                "arg": ["-c", script],
                "capture-output": True,
            },
        },
    )
    pid = started["pid"]

    deadline = time.monotonic() + POLL_LIMIT_S
    while time.monotonic() < deadline:
        status = agent(
            domain,
            {"execute": "guest-exec-status", "arguments": {"pid": pid}},
        )
        if status.get("exited"):
            for stream, key in ((sys.stdout, "out-data"), (sys.stderr, "err-data")):
                if key in status:
                    stream.write(
                        base64.b64decode(status[key]).decode("utf-8", "replace")
                    )
                    stream.flush()
            return status.get("exitcode", 0)
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit(f"{domain}: command still running after {POLL_LIMIT_S}s")


# The agent takes base64 inside a JSON argument, and Linux caps one argument at
# 128 KiB however much room the whole list has. 64 KiB of file is about 87 KiB
# encoded, which stays under it with room to spare.
PUSH_CHUNK_BYTES = 64 * 1024


def push(domain: str, source: str, destination: str) -> int:
    """Copy a local file into the guest, without using its network.

    Args:
        domain: The libvirt domain name.
        source: The file to send.
        destination: Where it lands in the guest.

    Returns:
        Zero when the whole file arrived.

    Raises:
        SystemExit: If the guest cannot open the destination.
    """
    payload = Path(source).read_bytes()
    handle = agent(
        domain,
        {
            "execute": "guest-file-open",
            "arguments": {"path": destination, "mode": "wb"},
        },
    )
    try:
        for start in range(0, len(payload), PUSH_CHUNK_BYTES):
            chunk = payload[start : start + PUSH_CHUNK_BYTES]
            agent(
                domain,
                {
                    "execute": "guest-file-write",
                    "arguments": {
                        "handle": handle,
                        "buf-b64": base64.b64encode(chunk).decode("ascii"),
                    },
                },
            )
    finally:
        agent(domain, {"execute": "guest-file-close", "arguments": {"handle": handle}})
    print(f"{source} -> {domain}:{destination} ({len(payload) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[2] == "push":
        sys.exit(push(sys.argv[1], sys.argv[3], sys.argv[4]))
    if len(sys.argv) < 3:
        raise SystemExit(__doc__.strip())
    sys.exit(run(sys.argv[1], " ".join(sys.argv[2:])))
