"""Reading a share link into a node.

The id it lands on is the part with reach: it names the outbound tag in the
xray configuration, it is the path segment the panel edits a node through, and
it is what "this link is already in the list" is decided on. Two servers that
read as one id are one node the person cannot have both of.
"""

from neutrino_hub.modules.xray.node_config import parse_share_link

# Links to servers that do not exist, with a placeholder credential in them.
FIRST_HOST = "ss://YWVzLTI1Ni1nY206eA==@203.0.113.10:5800#a"  # scan: allow
SECOND_HOST = "ss://YWVzLTI1Ni1nY206eA==@203.0.113.11:5800#b"  # scan: allow
FIRST_PORT = "ss://YWVzLTI1Ni1nY206eA==@example.com:5800#a"  # scan: allow
SECOND_PORT = "ss://YWVzLTI1Ni1nY206eA==@example.com:5900#b"  # scan: allow
NAMED_HOST = "ss://YWVzLTI1Ni1nY206eA==@c12s3.example.com:5800#a"  # scan: allow


def test_two_servers_on_one_network_are_two_nodes():
    """The id used to be the first label of the address, so every node a
    provider hands out by address read as the same one — `203.0.113.10` and
    `203.0.113.11` both as `203` — and the second was refused as a duplicate.
    """
    assert parse_share_link(FIRST_HOST).id != parse_share_link(SECOND_HOST).id


def test_one_host_on_two_ports_is_two_nodes():
    assert parse_share_link(FIRST_PORT).id != parse_share_link(SECOND_PORT).id


def test_the_same_link_always_reads_as_the_same_node():
    """Which is what lets the panel refuse a link that is already in the list,
    and what keeps an outbound tag pointing at the same server across a
    restart."""
    assert parse_share_link(FIRST_PORT).id == parse_share_link(FIRST_PORT).id


def test_a_named_host_keeps_its_name_in_the_id():
    """An id that is only a digest is one nobody can recognise in a URL."""
    assert parse_share_link(NAMED_HOST).id.startswith("c12s3_")
