"""Gitea's entry is reached at the port its server listens on."""

from neutrino_hub.modules.services.published import gitea_url


def test_the_url_takes_the_port_the_server_listens_on():
    """A ROOT_URL naming another port would send the connect stream there."""
    details = {"url": "http://192.168.100.7:3100/", "port": 3000}

    assert gitea_url(details) == "http://192.168.100.7:3000/"


def test_a_url_with_no_port_gets_the_listen_port():
    assert gitea_url({"url": "http://gateway.tail/", "port": 3000}) == (
        "http://gateway.tail:3000/"
    )


def test_a_report_missing_either_part_keeps_the_url_as_reported():
    assert gitea_url({"url": "http://gateway.tail:3000/"}) == (
        "http://gateway.tail:3000/"
    )
    assert gitea_url({"port": 3000}) == ""
