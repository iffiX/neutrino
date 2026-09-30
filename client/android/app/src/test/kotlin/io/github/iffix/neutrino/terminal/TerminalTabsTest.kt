package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.FakeSharedPreferences
import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.channel.ChannelInbound
import io.github.iffix.neutrino.channel.ChannelStreamRegistry
import io.github.iffix.neutrino.channel.FakeChannelSocket
import java.nio.ByteBuffer
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TerminalTabsTest {
    private val socket = FakeChannelSocket()
    private val registry = ChannelStreamRegistry(socket)
    private val preferences = FakeSharedPreferences()
    private val opener = StreamOpener { kind, args, hasBytes -> registry.open(kind, args, hasBytes) }

    private fun TestScope.tabs() = TerminalTabs(preferences, { opener }, backgroundScope)

    private fun opens(kind: String) = socket.sent("open").filter { it["kind"]!!.jsonPrimitive.content == kind }

    @Test
    fun aNewTabOpensItsShellAtTheFirstSizeWithItsSessionId() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        val open = opens("shell").single()
        assertEquals("d1", open["device_id"]!!.jsonPrimitive.content)
        assertEquals(id, open["session_id"]!!.jsonPrimitive.content)
        assertEquals(false, open["is_resumed"]!!.jsonPrimitive.boolean)
        assertEquals(24, open["rows"]!!.jsonPrimitive.int)
        assertEquals(emptyList<String>(), GoldenSchema.problems(JsonObject(open - "type"), "ChannelOpen"))
        assertEquals(TerminalPhase.OPEN, tabs.tabs.value.single().phase)
    }

    @Test
    fun aLaterSizeIsAResizeNamingTheShellStream() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.sized(id, 100, 30)
        val resize = opens("command").single()
        assertEquals("resize", resize["verb"]!!.jsonPrimitive.content)
        assertEquals(1, resize["shell"]!!.jsonPrimitive.int)
    }

    @Test
    fun outputIsKeptAndDrawnAgainForANewView() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        registry.takeBinary(ByteBuffer.allocate(6).putInt(1).put("$ ".toByteArray()).array())
        runCurrent()
        val seen = mutableListOf<String>()
        tabs.watch { tab, bytes -> seen += tab + ":" + String(bytes) }
        assertEquals(listOf("$id:$ "), seen)
    }

    @Test
    fun theSwitchSendsPersistAndKeepsTheSessionForTheNextStart() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.setPersistent(id, true)
        val persist = opens("command").single()
        assertEquals("persist", persist["verb"]!!.jsonPrimitive.content)
        assertEquals(true, persist["is_persistent"]!!.jsonPrimitive.boolean)
        assertEquals(id, persist["session_id"]!!.jsonPrimitive.content)
        assertEquals(null, persist["device_id"])
        val again = TerminalTabs(preferences, { opener }, backgroundScope)
        assertEquals(listOf(id), again.tabs.value.map { it.sessionId })
        assertEquals(TerminalPhase.DETACHED, again.tabs.value.single().phase)
    }

    @Test
    fun aKeptSessionAttachesAgainResumed() = runTest {
        val first = tabs()
        val id = first.create("b1", "d1", "Argon")
        first.sized(id, 80, 24)
        first.setPersistent(id, true)
        val again = TerminalTabs(preferences, { opener }, backgroundScope)
        again.sized(id, 80, 24)
        assertEquals(true, opens("shell").last()["is_resumed"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun closingAKeptTabEndsItsSession() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.setPersistent(id, true)
        tabs.close(id)
        val stop = opens("command").last()
        assertEquals("stop_session", stop["verb"]!!.jsonPrimitive.content)
        assertEquals(id, stop["session_id"]!!.jsonPrimitive.content)
        assertEquals(null, stop["device_id"])
        assertTrue(tabs.tabs.value.isEmpty())
    }

    @Test
    fun aSessionTheMachineNoLongerKeepsEnds() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        registry.takeClose(ChannelInbound.Close(1, "session_unknown", JsonObject(emptyMap())))
        runCurrent()
        assertEquals(TerminalPhase.ENDED, tabs.tabs.value.single().phase)
        assertEquals("session_unknown", tabs.tabs.value.single().note?.code)
    }

    @Test
    fun aHubThatIsNotConnectedLeavesTheTabDetached() = runTest {
        val tabs = TerminalTabs(preferences, { null }, backgroundScope)
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        assertEquals(TerminalPhase.DETACHED, tabs.tabs.value.single().phase)
        assertEquals("hub_unreachable", tabs.tabs.value.single().note?.code)
    }
}
