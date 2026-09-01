"""Reading the box's listening sockets out of ss.

What this guards is the exclusion: a service being reconfigured already holds
the ports its own configuration asks for, so counting them would make every
second save a conflict with itself.
"""

from neutrino_hub.system import listening_ports
from neutrino_hub.system.listening_ports import ListeningPortReader
from neutrino_hub.utils.subprocess_run import CommandResult

SS_OUTPUT = """\
udp   UNCONN 0 0    127.0.0.1:15353  0.0.0.0:*  users:(("xray",pid=1,fd=9))
tcp   LISTEN 0 4096   0.0.0.0:1080   0.0.0.0:*  users:(("xray",pid=1,fd=7))
tcp   LISTEN 0 4096   0.0.0.0:8080   0.0.0.0:*  users:(("nginx",pid=2,fd=6))
tcp   LISTEN 0 4096      [::]:22        [::]:*  users:(("sshd",pid=3,fd=4))
"""


def _reading(monkeypatch, output: str = SS_OUTPUT) -> ListeningPortReader:
    monkeypatch.setattr(
        listening_ports,
        "run",
        lambda command, **kwargs: CommandResult(
            command=command, exit_code=0, stdout=output, stderr=""
        ),
    )
    return ListeningPortReader()


def test_every_listening_port_is_read(monkeypatch):
    assert _reading(monkeypatch).ports() == {15353, 1080, 8080, 22}


def test_one_process_can_be_left_out(monkeypatch):
    assert _reading(monkeypatch).ports(ignoring="xray") == {8080, 22}


def test_an_address_with_colons_in_it_still_yields_its_port(monkeypatch):
    assert 22 in _reading(monkeypatch).ports()


def test_a_box_that_cannot_be_read_refuses_nothing(monkeypatch):
    assert _reading(monkeypatch, output="").ports() == set()
