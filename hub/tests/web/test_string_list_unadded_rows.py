"""A list editor's typed row and its frame's apply bar, held against ui_behavior.md.

What these pin: text typed into a StringListEditor and not added is held in
its frame's record while it is not blank; the bar lights for it, and its
Apply adds every typed row as Add does, then applies at the render that
draws them while the frame still holds a change; Reset empties the inputs;
and every frame that holds an editor gives its editors and its bar one record
and lights for a typed row.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
EDITOR = "components/string_list_editor.tsx"
# The frames that hold editors, and the name of each one's record; the
# mainland tree has no proxy page.
FRAMES = {
    "components/containers_panels.tsx": "containersRows",
    "pages/proxy_page.tsx": "routeRows",
    "pages/network_page.tsx": "interfaceRows",
}


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_the_editor_holds_its_typed_row_in_the_frame_while_it_is_not_blank():
    """In the lab a port typed into Ports without Add was dropped while the
    apply said Applied."""
    editor = flat(EDITOR)

    assert "const hold = useContext(UnaddedRowsContext)?.hold;" in editor
    assert "const isTyped = draft.trim().length > 0;" in editor
    assert (
        "hold( id, isTyped ? { add: () => { addTypedRef.current(); }, "
        'clear: () => { setDraft(""); }, } : null, );'
    ) in editor
    assert "return () => { hold(id, null); };" in editor
    add = editor[editor.index("const addTyped = () => {") :]
    add = add[: add.index("};") + 2]
    assert "if (entry.length === 0 || values.includes(entry)) { return; }" in add
    assert "onChange([...values, entry]);" in add
    assert "event.preventDefault(); addTyped();" in editor


def test_a_typed_row_lights_the_bar_and_its_apply_adds_the_rows_first():
    bar = flat("components/apply_bar.tsx")

    assert "const rows = useContext(UnaddedRowsContext);" in bar
    assert "const isLit = isDirty || hasRows;" in bar
    assert (
        "disabled={ isBusy || !isLit || blockedHint !== null || isApplyDisabled }"
        in bar
    )
    assert (
        "if (rows !== null && rows.hasRows) { rows.addAll(); "
        "setIsApplyAfterAdd(true); return; } onApply();"
    ) in bar
    assert (
        "if (!isApplyAfterAdd) { return; } setIsApplyAfterAdd(false); "
        "if (isDirty) { onApply(); }"
    ) in bar
    assert "rows?.clearAll(); onReset();" in bar
    assert (
        "disabled={ isBusy || !(hasChanges || hasRows) || blockedHint !== null }" in bar
    )
    assert "onClick={handleApply}" in bar
    assert "onClick={handleReset}" in bar


def test_every_frame_holding_an_editor_hands_it_one_record_and_lights_for_it():
    holders = sorted(
        str(path.relative_to(FRONTEND_SRC_DIR))
        for path in FRONTEND_SRC_DIR.rglob("*.tsx")
        if "<StringListEditor" in path.read_text(encoding="utf-8")
    )

    frames = {
        name: rows
        for name, rows in FRAMES.items()
        if (FRONTEND_SRC_DIR / name).exists()
    }
    assert holders == sorted(frames)
    for name, rows in frames.items():
        source = flat(name)
        assert f"const {rows} = useUnaddedRows();" in source, name
        assert f"<UnaddedRowsSection rows={{{rows}}}" in source, name
        assert f"isDirty || {rows}.hasRows ?" in source, name
    section = flat("components/unadded_rows_section.tsx")
    assert (
        "<section className={className}> "
        "<UnaddedRowsContext.Provider value={rows}> {children} "
        "</UnaddedRowsContext.Provider> </section>"
    ) in section
