package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.channel.ChannelInbound
import io.github.iffix.neutrino.channel.ChannelStreamRegistry
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.ChannelTerminalSession
import io.github.iffix.neutrino.channel.FakeChannelSocket
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
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
    private val opener = StreamOpener { kind, args, hasBytes -> registry.open(kind, args, hasBytes) }

    private fun TestScope.tabs() = TerminalTabs({ opener }, backgroundScope)

    private fun opens(kind: String) = socket.sent("open").filter { it["kind"]!!.jsonPrimitive.content == kind }

    private fun hub(vararg sessions: ChannelTerminalSession) = HubView(
        Samples.binding,
        connection = HubConnection.CONNECTED,
        terminals = listOf(ChannelTerminal("d1", "Argon", true, sessions.toList())),
    )

    private fun closeStream(id: Int, code: String = "") =
        registry.takeClose(ChannelInbound.Close(id, code, JsonObject(emptyMap())))

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
        assertEquals(id, tabs.active.value)
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
    fun theSwitchesSendPersistWithBothFlagsAndShowTheValuesAtOnce() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.persist(id, isPersistent = true, isShared = false)
        val persist = opens("command").single()
        assertEquals("persist", persist["verb"]!!.jsonPrimitive.content)
        assertEquals(id, persist["session_id"]!!.jsonPrimitive.content)
        assertEquals(true, persist["is_persistent"]!!.jsonPrimitive.boolean)
        assertEquals(false, persist["is_shared"]!!.jsonPrimitive.boolean)
        assertEquals(null, persist["device_id"])
        assertEquals(true, tabs.tabs.value.single().isPersistent)
    }

    @Test
    fun aTabThisPhoneDidNotOpenSendsNoPersist() = runTest {
        val tabs = tabs()
        tabs.take(listOf(hub(ChannelTerminalSession("s9", owner = "hub", isOwned = false, isShared = true))))
        tabs.sized("s9", 80, 24)
        tabs.persist("s9", isPersistent = true, isShared = true)
        assertTrue(opens("command").isEmpty())
        assertEquals(false, tabs.tabs.value.single().canPersist)
    }

    @Test
    fun aListedSessionGetsATabThatAttachesResumedWhenShown() = runTest {
        val tabs = tabs()
        tabs.take(listOf(hub(ChannelTerminalSession("s1", isOwned = true, isPersistent = true))))
        assertEquals("s1", tabs.active.value)
        assertEquals(TerminalPhase.DETACHED, tabs.tabs.value.single().phase)
        assertTrue(opens("shell").isEmpty())
        tabs.sized("s1", 80, 24)
        assertEquals(true, opens("shell").single()["is_resumed"]!!.jsonPrimitive.boolean)
        assertEquals(TerminalPhase.OPEN, tabs.tabs.value.single().phase)
    }

    @Test
    fun closingAKeptTabEndsItsSessionAndTheTabGoesOnceTheMachineAgrees() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.persist(id, isPersistent = true, isShared = false)
        tabs.close(id)
        val stop = opens("command").last()
        assertEquals("stop_session", stop["verb"]!!.jsonPrimitive.content)
        assertEquals(id, stop["session_id"]!!.jsonPrimitive.content)
        assertEquals(1, tabs.tabs.value.size)
        closeStream(stop["stream"]!!.jsonPrimitive.int)
        runCurrent()
        assertTrue(tabs.tabs.value.isEmpty())
    }

    @Test
    fun aClosedPlainTabStaysClosed() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.close(id)
        assertTrue(tabs.tabs.value.isEmpty())
        assertTrue(opens("command").isEmpty())
        tabs.take(listOf(hub(ChannelTerminalSession(id, isOwned = true))))
        assertTrue(tabs.tabs.value.isEmpty())
    }

    @Test
    fun aSessionTheMachineNoLongerKeepsEnds() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        closeStream(1, "session_unknown")
        runCurrent()
        assertEquals(TerminalPhase.ENDED, tabs.tabs.value.single().phase)
        assertEquals("session_unknown", tabs.tabs.value.single().note?.code)
    }

    @Test
    fun aHubThatIsNotConnectedLeavesTheTabDetached() = runTest {
        val tabs = TerminalTabs({ null }, backgroundScope)
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        assertEquals(TerminalPhase.DETACHED, tabs.tabs.value.single().phase)
        assertEquals("hub_unreachable", tabs.tabs.value.single().note?.code)
    }
}
