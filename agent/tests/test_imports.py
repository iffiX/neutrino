"""Every module in the tree imports, and the tree is the one that survived.

A move that broke a path fails here, and so does a module the prune was
meant to take out coming back by accident.
"""

import importlib
import pkgutil

import neutrino_agent

SURVIVING_MODULES = {
    "neutrino_agent.cli",
    "neutrino_agent.cli.connect",
    "neutrino_agent.cli.disconnect",
    "neutrino_agent.cli.entry",
    "neutrino_agent.cli.rdp",
    "neutrino_agent.cli.run",
    "neutrino_agent.cli.status",
    "neutrino_agent.cli.sync",
    "neutrino_agent.cli.wording",
    "neutrino_agent.constants",
    "neutrino_agent.control",
    "neutrino_agent.control.client",
    "neutrino_agent.control.server",
    "neutrino_agent.core",
    "neutrino_agent.core.channel",
    "neutrino_agent.core.commands",
    "neutrino_agent.core.engine",
    "neutrino_agent.core.enrollment",
    "neutrino_agent.core.loop",
    "neutrino_agent.core.metrics",
    "neutrino_agent.core.self_update",
    "neutrino_agent.core.session",
    "neutrino_agent.core.store",
    "neutrino_agent.core.version",
    "neutrino_agent.core.ws_client",
    "neutrino_agent.modules",
    "neutrino_agent.modules.base",
    "neutrino_agent.modules.installers",
    "neutrino_agent.modules.package",
    "neutrino_agent.modules.rustdesk",
    "neutrino_agent.modules.system_package",
    "neutrino_agent.platforms",
    "neutrino_agent.platforms.base",
    "neutrino_agent.platforms.detect",
    "neutrino_agent.platforms.linux",
    "neutrino_agent.rdp",
    "neutrino_agent.rdp.constants",
    "neutrino_agent.rdp.host",
}


def found_modules() -> set:
    return {
        found.name
        for found in pkgutil.walk_packages(neutrino_agent.__path__, "neutrino_agent.")
    }


def test_every_module_imports():
    for name in sorted(found_modules()):
        importlib.import_module(name)


def test_the_tree_is_the_one_that_survived_the_prune():
    assert found_modules() == SURVIVING_MODULES
