"""``nagent connect``: joining a hub, and every way the join is refused."""

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.core.channel import GatewayVersionRefused
from tests.conftest import link_for


def test_connect_refuses_a_newer_agent_visibly(config_path, monkeypatch):
    def refuse(self, path, payload):
        raise GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")

    monkeypatch.setattr(enrollment.GatewayHttpChannel, "post", refuse)
    link = link_for({"urls": ["http://127.0.0.1:9"], "token": "ticket", "fp": ""})

    with pytest.raises(enrollment.EnrollmentError) as refusal:
        enrollment.enroll(link)

    assert "this agent (0.2.0) is newer than the hub (0.1.0)" in str(refusal.value)
    assert "update the hub first" in str(refusal.value)
    assert "gateway_url" not in enrollment.load_config()
