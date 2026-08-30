"""What a module says installing would do, and the gate in front of it.

Adding the repository a distribution keeps a package in is part of installing
it. Compiling a kernel module against the running kernel is not, and neither
is trusting a repository the distribution does not ship. The difference is
what this mechanism exists to carry.
"""

import pytest

from neutrino_hub.system.constants import (
    SYSTEM_CONSENT_KERNEL_MODULE_BUILD,
    SYSTEM_CONSENT_THIRD_PARTY_REPOSITORY,
)
from neutrino_hub.system.provisioning import (
    ProvisionConsent,
    ProvisionPlan,
    plan_for,
)


class SilentProvisioner:
    """A module that only installs packages, and so answers nothing."""


class TalkativeProvisioner:
    """A module that would compile something."""

    def plan(self) -> ProvisionPlan:
        return ProvisionPlan(
            consents=(
                ProvisionConsent(
                    code=SYSTEM_CONSENT_KERNEL_MODULE_BUILD,
                    detail={"packages": ["zfs-dkms"], "kernel": "6.1.0-18-amd64"},
                ),
            )
        )


def test_a_module_that_only_installs_packages_is_not_asked_about():
    assert plan_for(SilentProvisioner()).is_consent_needed is False
    assert plan_for(SilentProvisioner()).consents == ()


def test_a_module_that_would_compile_says_so_with_what_it_needs():
    plan = plan_for(TalkativeProvisioner())
    assert plan.is_consent_needed is True
    consent = plan.consents[0]
    assert consent.code == SYSTEM_CONSENT_KERNEL_MODULE_BUILD
    assert consent.detail["kernel"] == "6.1.0-18-amd64"


def test_a_consent_carries_no_sentence():
    """Wording is the panel's, so a code and its values are all that travels."""
    consent = ProvisionConsent(code=SYSTEM_CONSENT_THIRD_PARTY_REPOSITORY)
    assert set(vars(consent)) == {"code", "detail"}
    assert consent.detail == {}


def test_a_consent_is_frozen():
    """A plan is a description; nothing downstream edits what it was told."""
    consent = ProvisionConsent(code=SYSTEM_CONSENT_KERNEL_MODULE_BUILD)
    with pytest.raises(Exception):
        consent.code = "something_else"
