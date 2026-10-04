package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_MAX_MS
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_QUIET_MS
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
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
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

    private fun typed(): String = synchronized(socket) {
        socket.binaries.joinToString("") { String(it, CHANNEL_STREAM_ID_BYTES, it.size - CHANNEL_STREAM_ID_BYTES) }
    }

    private fun TestScope.output(text: String) {
        val bytes = text.toByteArray()
        registry.takeBinary(ByteBuffer.allocate(CHANNEL_STREAM_ID_BYTES + bytes.size).putInt(1).put(bytes).array())
        runCurrent()
    }

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
    fun keysReachTheShellInTheOrderTyped() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        val keys = (0 until 200).map { "k$it;" }
        for (key in keys) tabs.input(id, key.toByteArray())
        runCurrent()
        for (step in 0 until keys.sumOf { it.length }) {
            registry.takeCredit(ChannelInbound.Credit(1, 1))
            runCurrent()
        }
        assertEquals(keys.joinToString(""), typed())
    }

    @Test
    fun keysReachTheShellInTheOrderTypedOnAPoolOfThreads() = runBlocking {
        val scope = CoroutineScope(Dispatchers.Default + Job())
        try {
            val tabs = TerminalTabs({ opener }, scope)
            val id = tabs.create("b1", "d1", "Argon")
            tabs.sized(id, 80, 24)
            val keys = (0 until 200).map { "k$it;" }
            val expected = keys.joinToString("")
            for (key in keys) tabs.input(id, key.toByteArray())
            withTimeout(10_000) {
                while (typed().length < expected.length) {
                    registry.takeCredit(ChannelInbound.Credit(1, 3))
                    delay(1)
                }
            }
            assertEquals(expected, typed())
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun clearSendsCtrlCAfterTheKeysBeforeIt() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        registry.takeCredit(ChannelInbound.Credit(1, 64))
        tabs.input(id, "yes".toByteArray())
        tabs.clear(id)
        runCurrent()
        assertEquals("yes\u0003", typed())
    }

    @Test
    fun clearDropsAFloodWholeAndDrawsTheFirstOutputAfterTheQuiet() = runTest {
        val tabs = TerminalTabs({ opener }, backgroundScope, clock = { testScheduler.currentTime })
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        val seen = StringBuilder()
        tabs.watch { _, bytes -> seen.append(String(bytes)) }
        output("flood ")
        assertEquals("flood ", seen.toString())
        tabs.clear(id)
        repeat(50) {
            advanceTimeBy(100)
            output("y ")
        }
        advanceTimeBy(CLIENT_TERMINAL_CLEAR_QUIET_MS - 1)
        output("tail ")
        advanceTimeBy(CLIENT_TERMINAL_CLEAR_QUIET_MS)
        output("$ ")
        assertEquals("flood $ ", seen.toString())
        val again = StringBuilder()
        tabs.watch { _, bytes -> again.append(String(bytes)) }
        assertEquals("$ ", again.toString())
    }

    @Test
    fun aStreamThatNeverGoesQuietIsDrawnAgainAfterTheCap() = runTest {
        val tabs = TerminalTabs({ opener }, backgroundScope, clock = { testScheduler.currentTime })
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        val seen = StringBuilder()
        tabs.watch { _, bytes -> seen.append(String(bytes)) }
        val end = testScheduler.currentTime + CLIENT_TERMINAL_CLEAR_MAX_MS
        tabs.clear(id)
        val step = CLIENT_TERMINAL_CLEAR_QUIET_MS / 5
        while (testScheduler.currentTime + step < end) {
            advanceTimeBy(step)
            output("y ")
        }
        assertEquals("", seen.toString())
        advanceTimeBy(end - testScheduler.currentTime)
        output("still ")
        assertEquals("still ", seen.toString())
    }

    @Test
    fun clearingShowsUntilTheStreamIsQuiet() = runTest {
        val tabs = TerminalTabs({ opener }, backgroundScope, clock = { testScheduler.currentTime })
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.watch { _, _ -> }
        assertEquals(emptySet<String>(), tabs.clearing.value)
        tabs.clear(id)
        assertEquals(setOf(id), tabs.clearing.value)
        repeat(30) {
            advanceTimeBy(100)
            output("y ")
            assertEquals(setOf(id), tabs.clearing.value)
        }
        advanceTimeBy(CLIENT_TERMINAL_CLEAR_QUIET_MS - 1)
        runCurrent()
        assertEquals(setOf(id), tabs.clearing.value)
        advanceTimeBy(1)
        runCurrent()
        assertEquals(emptySet<String>(), tabs.clearing.value)
    }

    @Test
    fun clearingEndsAtTheCap() = runTest {
        val tabs = TerminalTabs({ opener }, backgroundScope, clock = { testScheduler.currentTime })
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        tabs.watch { _, _ -> }
        val end = testScheduler.currentTime + CLIENT_TERMINAL_CLEAR_MAX_MS
        tabs.clear(id)
        val step = CLIENT_TERMINAL_CLEAR_QUIET_MS / 5
        while (testScheduler.currentTime + step < end) {
            advanceTimeBy(step)
            output("y ")
        }
        assertEquals(setOf(id), tabs.clearing.value)
        advanceTimeBy(end - testScheduler.currentTime)
        runCurrent()
        assertEquals(emptySet<String>(), tabs.clearing.value)
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
