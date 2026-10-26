package io.github.iffix.neutrino.screen

import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelServiceEntry
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalPortDialogTest {
    private val web =
        ChannelServiceEntry("a_web", "web", "A", JsonObject(emptyMap()), appId = "a", name = "web", localPort = 27311)
    private val udp = ChannelServiceEntry(
        "a_port_7777_udp",
        "port",
        "A",
        JsonObject(mapOf("protocol" to JsonPrimitive("udp"))),
        appId = "a",
        name = "port_7777_udp",
        localPort = 25001,
    )

    @Test
    fun aNumberOutOfRangeDisablesSaveWithTheRangeAsItsReason() {
        assertEquals("ui.reason.port_range", localPortReasonKey(listOf("999")))
        assertEquals("ui.reason.port_range", localPortReasonKey(listOf("27311", "65536")))
    }

    @Test
    fun anEmptyFieldOrANumberInRangeLeavesSaveEnabled() {
        assertNull(localPortReasonKey(listOf("", "1024", "65535")))
    }

    @Test
    fun theHubsNumberOrNothingGoesBackToTheHubsAndAnotherIsThePersons() {
        assertEquals(
            mapOf("a_web" to null, "a_port_7777_udp" to 28080),
            numbersOf(listOf(web, udp), mapOf("a_web" to "27311", "a_port_7777_udp" to "28080")),
        )
        assertEquals(
            mapOf("a_web" to null, "a_port_7777_udp" to null),
            numbersOf(listOf(web, udp), mapOf("a_web" to "")),
        )
    }

    @Test
    fun aUdpEntryIsNamedSo() {
        assertEquals("web", kindOf(web))
        assertEquals("port/udp", kindOf(udp))
    }

    @Test
    fun cancelComesBeforeSave() {
        assertTrue(cancelBeforeSave("LocalPortDialog.kt"))
        assertTrue(cancelBeforeSave("RemoteDesktopDialog.kt"))
        assertTrue(cancelBeforeSave("SettingsScreen.kt"))
    }

    private fun cancelBeforeSave(file: String): Boolean {
        val source = RepositoryFiles.text("client/android/app/src/main/kotlin/io/github/iffix/neutrino/screen/$file")
        val cancel = source.indexOf("words.word(\"ui.cancel\")")
        val save = source.indexOf("words.word(\"ui.save\")")
        return cancel in 0 until save
    }
}
