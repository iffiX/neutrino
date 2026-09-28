"""Counting a port's established connections in what netstat printed.

Windows joins an address to its port with a colon and a Mac with a dot; a
listening socket and a closing one are not peers.
"""

from neutrino_agent.rdp.netstat import established_count


def test_windows_rows_join_the_port_with_a_colon():
    printed = (
        "  TCP    0.0.0.0:21118          0.0.0.0:0              LISTENING\n"
        "  TCP    192.0.2.10:21118       192.0.2.20:50123       ESTABLISHED\n"
        "  TCP    [::1]:21118            [::1]:50126            ESTABLISHED\n"
        "  TCP    192.0.2.10:21118       192.0.2.23:50127       TIME_WAIT\n"
    )

    assert (
        established_count(printed, 21118, established="ESTABLISHED", separator=":") == 2
    )


def test_a_macs_rows_join_the_port_with_a_dot():
    printed = (
        "tcp4  0  0  192.0.2.10.21118  192.0.2.20.50123  ESTABLISHED\n"
        "tcp6  0  0  fe80::1%en0.21118  fe80::2%en0.50124  ESTABLISHED\n"
        "tcp4  0  0  *.21118  *.*  LISTEN\n"
        "tcp4  0  0  192.0.2.10.22  192.0.2.20.50125  ESTABLISHED\n"
    )

    assert (
        established_count(printed, 21118, established="ESTABLISHED", separator=".") == 2
    )
    assert established_count(printed, 22, established="ESTABLISHED", separator=".") == 1
