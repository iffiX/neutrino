package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.RepositoryFiles
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalMenuTest {
    private val page = RepositoryFiles.text("client/android/app/src/main/assets/terminal/terminal.js")

    @Test
    fun clearSendsCtrlCToTheShellBeforeItClearsTheScreen() {
        val clear = page.substringAfter("labels.clear,").substringBefore("],")
        val ctrlC = clear.indexOf("window.NeutrinoBridge.input(id, toBase64(\"\\x03\"));")
        val wipe = clear.indexOf("pane.term.clear();")
        assertTrue(ctrlC >= 0)
        assertTrue(ctrlC < wipe)
    }
}
