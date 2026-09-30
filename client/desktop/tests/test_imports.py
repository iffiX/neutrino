"""Every module in the tree imports; a move that broke a path fails here."""

import importlib
import pkgutil

import neutrino_client


def test_every_module_imports():
    for found in pkgutil.walk_packages(neutrino_client.__path__, "neutrino_client."):
        importlib.import_module(found.name)
