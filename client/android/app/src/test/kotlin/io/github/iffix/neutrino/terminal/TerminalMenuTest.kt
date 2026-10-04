package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_DROP_MS
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
        val window = clearPane.indexOf("pane.dropUntil = Date.now() + CLEAR_DROP_MS;")
        val told = clearPane.indexOf("window.NeutrinoBridge.clear(id);")
        val wipe = clearPane.indexOf("pane.term.clear();")
        assertTrue(emptied >= 0 && window >= 0)
        assertTrue(emptied < told && window < told)
        assertTrue(told < wipe)
        assertTrue(page.contains("[labels.clear, true, () => clearPane(id, pane)]"))
    }

    @Test
    fun thePageDropsOutputForTheSameSecondAsTheApp() {
        val drop = Regex("""const CLEAR_DROP_MS = (\d+);""").find(page)?.groupValues?.get(1)?.toLong()
        assertEquals(CLIENT_TERMINAL_CLEAR_DROP_MS, drop)
        val write = page.substringAfter("write(id, encoded) {").substringBefore("\n    },")
        assertTrue(write.contains("Date.now() < pane.dropUntil) return;"))
        assertTrue(write.contains("pane.queue.push("))
    }
}
