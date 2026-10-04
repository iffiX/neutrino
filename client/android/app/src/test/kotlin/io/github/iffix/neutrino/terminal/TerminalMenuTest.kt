package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_MAX_MS
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_QUIET_MS
import io.github.iffix.neutrino.RepositoryFiles
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalMenuTest {
    private val page = RepositoryFiles.text("client/android/app/src/main/assets/terminal/terminal.js")

    private val clearPane = page.substringAfter("function clearPane(id, pane) {").substringBefore("\n  }")

    @Test
    fun clearDropsWhatWaitsAndTellsTheAppBeforeItClearsTheScreen() {
        val emptied = clearPane.indexOf("pane.queue.length = 0;")
        val window = clearPane.indexOf("pane.drop = { since: now, last: now };")
        val told = clearPane.indexOf("window.NeutrinoBridge.clear(id);")
        val wipe = clearPane.indexOf("pane.term.clear();")
        assertTrue(emptied >= 0 && window >= 0)
        assertTrue(emptied < told && window < told)
        assertTrue(told < wipe)
        assertTrue(page.contains("[labels.clear, true, () => clearPane(id, pane)]"))
    }

    @Test
    fun thePageDropsOutputByTheSameQuietAndCapAsTheApp() {
        assertEquals(CLIENT_TERMINAL_CLEAR_QUIET_MS, constant("CLEAR_QUIET_MS"))
        assertEquals(CLIENT_TERMINAL_CLEAR_MAX_MS, constant("CLEAR_MAX_MS"))
        val dropped = page.substringAfter("function isDropped(pane) {").substringBefore("\n  }")
        assertTrue(dropped.contains("now - drop.last < CLEAR_QUIET_MS && now - drop.since < CLEAR_MAX_MS"))
        assertTrue(dropped.contains("drop.last = now;"))
        val write = page.substringAfter("write(id, encoded) {").substringBefore("\n    },")
        assertTrue(write.contains("if (!pane || isDropped(pane)) return;"))
        assertTrue(write.contains("pane.queue.push("))
    }

    @Test
    fun thePaneShowsTheClearingWordAtOnceAndTheAppTakesItAway() {
        val shown = clearPane.indexOf("showNote(pane, true);")
        assertTrue(shown >= 0 && shown < clearPane.indexOf("window.NeutrinoBridge.clear(id);"))
        val clearing = page.substringAfter("clearing(json) {").substringBefore("\n    },")
        assertTrue(clearing.contains("showNote(panes[key], ids.includes(key));"))
        val note = page.substringAfter("function showNote(pane, isShown) {").substringBefore("\n  }")
        assertTrue(note.contains("pane.note.textContent = labels.clearing;"))
        assertTrue(note.contains("pane.note.hidden = !isShown;"))
        assertTrue(page.contains("note.style.fontFamily = FONT;"))
        assertTrue(!clearPane.contains("pane.term.write("))
    }

    private fun constant(name: String): Long? =
        Regex("""const $name = (\d+);""").find(page)?.groupValues?.get(1)?.toLong()
}
