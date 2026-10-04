package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.RepositoryFiles
import java.awt.Font
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalViewTest {
    private val assets = "client/android/app/src/main/assets/terminal"
    private val script = RepositoryFiles.text("$assets/terminal.js")
    private val page = RepositoryFiles.text("$assets/index.html")

    private val families: List<String> =
        Regex("""const FONT = '(.*)';""").find(script)?.groupValues?.get(1).orEmpty()
            .split(",").map { it.trim().trim('"') }

    private val faces: Map<String, List<Font>> =
        Regex("""@font-face \{ font-family: "([^"]+)"; src: url\("([^"]+)"\)""").findAll(page)
            .groupBy({ it.groupValues[1] }, { load(it.groupValues[2]) })

    @Test
    fun theFamilyListsTheSymbolFacesAfterTheMonospaceFace() {
        assertEquals(
            listOf("MesloLGS NF", "Neutrino Symbols 2", "Neutrino Symbols", "ui-monospace", "monospace"),
            families,
        )
    }

    @Test
    fun theAppCarriesAFaceForEverySymbolOfAPrompt() {
        for (symbol in "▶ ✻ ● ─ ╭ ⏵ ⎿ ⠋ ✳".split(" ")) {
            val carried = families.flatMap { faces[it].orEmpty() }
            assertTrue("no carried face draws $symbol", carried.any { it.canDisplayUpTo(symbol) == -1 })
        }
    }

    @Test
    fun aPaneHasNoPaddingSoItsLastRowIsInsideIt() {
        val pane = page.substringAfter(".pane {").substringBefore("}")
        assertTrue(pane.contains("inset: 6px;"))
        assertTrue(!pane.contains("padding"))
    }

    private fun load(url: String): Font {
        val file = when {
            url.startsWith("vendor/") -> RepositoryFiles.file("hub/frontend/src/fonts/" + url.removePrefix("vendor/"))
            else -> RepositoryFiles.file("$assets/$url")
        }
        return Font.createFont(Font.TRUETYPE_FONT, file)
    }
}
