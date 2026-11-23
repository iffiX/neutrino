"""The Ollama tab's Models: the context length under a loaded model's memory, held against ui_text.md.

What these pin: the line says what ui_text.md writes in both languages,
filling ``{tokens}``; the memory cell draws it under the model's numbers
from the view's ``context_length``, only while it names one, so the cell
keeps its column and a model not in memory draws nothing.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
PANELS_PATH = FRONTEND_SRC_DIR / "components/ollama_panels.tsx"
WORDS = {"en": "Context {tokens}", "zh-CN": "上下文 {tokens}"}


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_line_says_what_ui_text_writes(language):
    worded = json.loads((LOCALES_DIR / language / "modules.json").read_text("utf-8"))
    assert worded["ui.ollama.memory_context"] == WORDS[language]


def test_the_memory_cell_draws_the_context_length_under_its_numbers():
    source = " ".join(PANELS_PATH.read_text(encoding="utf-8").split())
    cell = source[source.index("function MemoryCell(") :]
    cell = cell[: cell.index("function memoryShare(")]
    numbers = cell.index('className="ollama_memory_numbers"')
    line = cell.index("model.context_length > 0 && (")
    assert numbers < line
    assert (
        't("ui.ollama.memory_context", { tokens: model.context_length })' in cell[line:]
    )
    assert cell.index("if (!model.is_loaded)") < numbers
