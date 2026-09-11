"""Every typed refusal the hub answers with, held against the catalogs.

A code with no sentence reaches the panel as the code itself, which is the
one failure a review cannot see: the route is right, the status is right, and
the screen says ``dhcp_range_reversed``. This walks the sources for every
code a raise site names and asserts English words it.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "neutrino_hub"
LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend/src/locales"

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
# The calls that carry a code as their first argument. Everything else names
# one under a ``code`` key or a ``code=`` argument, which is read as well.
CODED_CALLS = frozenset(
    {
        "AgentArtifactFetchError",
        "AiAccountRefusedError",
        "KeyMaterialError",
        "PasswordRefusedError",
        "ServiceFieldInvalidError",
        "StreamRefusedError",
        "_bad_gateway",
        "_bad_request",
        "_coded_bad_request",
        "_refusal",
    }
)
# Codes that name a step of the first run rather than a refusal; the setup
# page words those under ``ui.setup.step_``.
STEP_CODES = frozenset({"install_module", "panel_password", "write_answers"})


def string_constants() -> dict:
    """Every module-level string constant in the package, by name."""
    constants: dict = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    constants[target.id] = node.value.value
    return constants


def raised_codes() -> set:
    """Every code a raise site in the package names."""
    constants = string_constants()

    def resolved(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.Attribute):
            return constants.get(node.attr)
        return None

    codes: set = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "code":
                        codes.add(resolved(value))
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if name in CODED_CALLS and node.args:
                    codes.add(resolved(node.args[0]))
                for keyword in node.keywords:
                    if keyword.arg == "code":
                        codes.add(resolved(keyword.value))
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    if not isinstance(statement, ast.Assign):
                        continue
                    target = statement.targets[0]
                    if isinstance(target, ast.Name) and target.id == "code":
                        codes.add(resolved(statement.value))
    named = {code for code in codes if code and CODE_PATTERN.match(code)}
    return named - STEP_CODES


def worded_codes() -> set:
    """Every code English has a sentence for."""
    worded: set = set()
    for path in (LOCALES_DIR / WEB_DEFAULT_LANGUAGE).glob("*.json"):
        table = json.loads(path.read_text(encoding="utf-8"))
        worded |= {key[len("code.") :] for key in table if key.startswith("code.")}
    return worded


@pytest.mark.parametrize("code", sorted(raised_codes()))
def test_every_code_the_hub_raises_is_worded(code):
    assert code in worded_codes()
