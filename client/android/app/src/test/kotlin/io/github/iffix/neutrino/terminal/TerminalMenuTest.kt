package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.RepositoryFiles
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalMenuTest {
    private val page = RepositoryFiles.text("client/android/app/src/main/assets/terminal/terminal.js")

    private val clearPane = page.substringAfter("function clearPane(id, pane) {").substringBefore("\n  }")

    private val showClearing = page.substringAfter("function showClearing(pane, isClearing) {").substringBefore("\n  }")

    private val listed = page.substringAfter("    clearing(json) {").substringBefore("\n    },")

    @Test
    fun clearEntersTheClearingStateBeforeItTellsTheApp() {
        val entered = clearPane.indexOf("showClearing(pane, true);")
        val asked = clearPane.indexOf("pane.isClearAsked = true;")
        val told = clearPane.indexOf("window.NeutrinoBridge.clear(id)")
        assertTrue(entered >= 0 && entered < asked && asked < told)
        assertTrue(page.contains("[labels.clear, true, () => clearPane(id, pane)]"))
    }

    @Test
    fun nothingThatArrivesWhileClearingIsDrawn() {
        val write = page.substringAfter("    write(id, encoded) {").substringBefore("\n    },")
        assertTrue(write.contains("if (!pane || pane.isClearing) return;"))
        assertTrue(write.contains("pane.queue.push("))
        assertTrue(showClearing.contains("pane.queue.length = 0;"))
        assertTrue(!page.contains("CLEAR_QUIET_MS"))
    }

    @Test
    fun thePaneIsWipedWhenClearingStartsAndWhenItEnds() {
        assertTrue(page.contains("""const TERMINAL_ERASE = "\x1b[2J\x1b[3J\x1b[H";"""))
        assertTrue(showClearing.contains("pane.isClearing = isClearing;"))
        assertTrue(showClearing.contains("pane.term.write(TERMINAL_ERASE);"))
        assertTrue(!page.contains("term.clear()"))
    }

    @Test
    fun thePaneShowsTheClearingWordWhileItClears() {
        assertTrue(showClearing.contains("pane.note.textContent = labels.clearing;"))
        assertTrue(showClearing.contains("pane.note.hidden = !isClearing;"))
        assertTrue(page.contains("note.style.fontFamily = FONT;"))
    }

    @Test
    fun aRefusedClearOrTheAppsEndOfTheDropLeavesTheClearingState() {
        assertTrue(clearPane.contains("if (!window.NeutrinoBridge.clear(id)) showClearing(pane, false);"))
        assertTrue(listed.contains("if (!pane.isClearing) showClearing(pane, true);"))
        assertTrue(listed.contains("} else if (pane.isClearing && !pane.isClearAsked) {"))
        assertTrue(listed.indexOf("pane.isClearAsked = false;") < listed.indexOf("} else if"))
    }
}
