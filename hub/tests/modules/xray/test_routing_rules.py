"""What the direct lists accept, and what they send back.

The address list is the one that matters: xray refuses the whole configuration
over a single unparseable line, which used to mean the apply stopped before the
firewall and the resolver were touched.
"""

import pytest

from neutrino_hub.modules.xray.routing_rules import (
    check_direct_address,
    check_direct_domain,
)


@pytest.mark.parametrize(
    "entry",
    ["192.0.2.1", "192.0.2.0/24", "2001:db8::/32", "geoip:cn", "ext:geoip.dat:cn"],
)
def test_an_address_xray_loads_is_accepted(entry):
    check_direct_address(entry)


@pytest.mark.parametrize("entry", ["", "  ", "192.0.2.300", "192.0.2.0/33", "cn"])
def test_an_address_xray_refuses_is_refused_here(entry):
    with pytest.raises(ValueError):
        check_direct_address(entry)


@pytest.mark.parametrize(
    "entry",
    ["example.com", "domain:example.com", "geosite:cn", "regexp:^.+\\.example\\.com$"],
)
def test_a_domain_xray_loads_is_accepted(entry):
    check_direct_domain(entry)


@pytest.mark.parametrize("entry", ["", "regexp:(unclosed", "two words"])
def test_a_domain_that_matches_nothing_is_refused(entry):
    """A regular expression that does not compile stops xray from loading; the
    other two are lines that load and then match no traffic at all, which reads
    on the page as a rule that is in force."""
    with pytest.raises(ValueError):
        check_direct_domain(entry)
