"""The Add module dialog's cards, held against ui_behavior.md.

What these pin: every card the machine can run draws its check, and the
panel reads no ``is_available`` from the catalog.
"""

from pathlib import Path

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_a_card_draws_its_check_whenever_the_machine_can_run_its_module():
    modal = flat("components/module_catalog_modal.tsx")

    assert "const isCheckable = entry.is_supported;" in modal
    assert "{isCheckable && ( <input" in modal


def test_the_panel_reads_no_is_available_from_the_catalog():
    modal = flat("components/module_catalog_modal.tsx")
    types = flat("api_types.ts")
    entry = types[types.index("export interface ModuleCatalogEntry {") :]
    entry = entry[: entry.index("}")]

    assert "is_available" not in modal
    assert "is_available" not in entry
