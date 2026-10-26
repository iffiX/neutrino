package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_MAX_MS
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_QUIET_MS
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.TRANSPORT_RECORD_DATA
import io.github.iffix.neutrino.TRANSPORT_RECORD_RESIZE
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelTerminal
import io.github.iffix.neutrino.channel.ChannelTerminalSession
import io.github.iffix.neutrino.channel.HubConnection
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.channel.Samples
import io.github.iffix.neutrino.transport.FakeTransport
import io.github.iffix.neutrino.transport.MemoryConnection
import io.github.iffix.neutrino.transport.TransportRecord
import io.github.iffix.neutrino.transport.TransportStream
import java.io.DataInputStream
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TerminalTabsTest {
    private val transport = FakeTransport().also { it.start("/data", "bb".repeat(32)) }
    private val shells = LinkedBlockingQueue<Pair<JsonObject, MemoryConnection>>()
    private val persisted = CopyOnWriteArrayList<Triple<String, Boolean, Boolean>>()
    private val stopped = CopyOnWriteArrayList<String>()
    private var stopAnswer: ChannelResult<JsonObject> = ChannelResult.Ok(JsonObject(emptyMap()))

    private val hub = object : TerminalHub {
        override fun open(open: JsonObject) = TransportStream.open(transport, transport.secret, "b1", open)

        override suspend fun persist(
            sessionId: String,
            isPersistent: Boolean,
            isShared: Boolean,
        ): ChannelResult<JsonObject> {
            persisted += Triple(sessionId, isPersistent, isShared)
            return ChannelResult.Ok(JsonObject(emptyMap()))
        }

        override suspend fun stopSession(sessionId: String): ChannelResult<JsonObject> {
            stopped += sessionId
            return stopAnswer
        }
    }

    init {
        transport.serve = { open, end ->
            FakeTransport.accept(end)
            shells.put(open to end)
        }
    }

    private fun TestScope.tabs(clock: () -> Long = { testScheduler.currentTime }) =
        TerminalTabs({ hub }, backgroundScope, clock)

    private fun hubView(vararg sessions: ChannelTerminalSession) = HubView(
        Samples.binding,
        connection = HubConnection.CONNECTED,
        terminals = listOf(
            ChannelTerminal("d1", "Argon", isOnline = true, accounts = listOf("iffi"), sessions = sessions.toList()),
        ),
    )

    private fun TestScope.eventually(check: () -> Boolean) {
        val until = System.currentTimeMillis() + 5000
        while (System.currentTimeMillis() < until) {
            runCurrent()
            if (check()) return
            Thread.sleep(5)
        }
        throw AssertionError("never")
    }

    private fun TestScope.output(end: MemoryConnection, text: String) {
        TransportRecord.write(end.output, TRANSPORT_RECORD_DATA, text.toByteArray())
        val app = end.other ?: error("no app end")
        Thread.sleep(5)
        eventually { app.isDrained }
    }

    private fun records(end: MemoryConnection, count: Int): List<TransportRecord> {
        val input = DataInputStream(end.input)
        return List(count) { TransportRecord.read(input) ?: error("the stream ended") }
    }

    private fun TestScope.opened(tabs: TerminalTabs, account: String = "iffi"): Pair<String, MemoryConnection> {
        val id = tabs.create("b1", "d1", "Argon", account)
        tabs.sized(id, 80, 24)
        val (_, end) = shells.poll(5, TimeUnit.SECONDS) ?: error("no shell")
        eventually { tabs.tabs.value.single { it.sessionId == id }.phase == TerminalPhase.OPEN }
        return id to end
    }

    @Test
    fun aNewTabOpensItsShellAsThePickedAccountAtTheFirstSizeWithItsSessionId() = runTest {
        val tabs = tabs()
        val id = tabs.create("b1", "d1", "Argon", "lab")
        tabs.sized(id, 80, 24)
        val (open, _) = shells.poll(5, TimeUnit.SECONDS) ?: error("no shell")
        assertEquals("shell", open["kind"]!!.jsonPrimitive.content)
        assertEquals("d1", open["device_id"]!!.jsonPrimitive.content)
        assertEquals("lab", open["account"]!!.jsonPrimitive.content)
        assertEquals(id, open["session_id"]!!.jsonPrimitive.content)
        assertEquals(false, open["is_resumed"]!!.jsonPrimitive.boolean)
        assertEquals(24, open["rows"]!!.jsonPrimitive.int)
        eventually { tabs.tabs.value.single().phase == TerminalPhase.OPEN }
        assertEquals(id, tabs.active.value)
    }

    @Test
    fun aLaterSizeIsAResizeRecordOnTheShellsStream() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        tabs.sized(id, 100, 30)
        val resize = records(end, 1).single()
        assertEquals(TRANSPORT_RECORD_RESIZE, resize.type)
        assertEquals(100, resize.json["cols"]!!.jsonPrimitive.int)
        assertEquals(30, resize.json["rows"]!!.jsonPrimitive.int)
    }

    @Test
    fun outputIsKeptAndDrawnAgainForANewView() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        output(end, "$ ")
        val seen = mutableListOf<String>()
        tabs.watch { tab, bytes -> seen += tab + ":" + String(bytes) }
        assertEquals(listOf("$id:$ "), seen)
    }

    @Test
    fun theSwitchesSendPersistWithBothFlagsAndShowTheValuesAtOnce() = runTest {
        val tabs = tabs()
        val (id, _) = opened(tabs)
        tabs.persist(id, isPersistent = true, isShared = false)
        assertEquals(true, tabs.tabs.value.single().isPersistent)
        runCurrent()
        assertEquals(listOf(Triple(id, true, false)), persisted)
    }

    @Test
    fun aTabThisPhoneDidNotOpenSendsNoPersist() = runTest {
        val tabs = tabs()
        tabs.take(listOf(hubView(ChannelTerminalSession("s9", owner = "hub", isOwned = false, isShared = true))))
        tabs.sized("s9", 80, 24)
        eventually { tabs.tabs.value.single().phase == TerminalPhase.OPEN }
        tabs.persist("s9", isPersistent = true, isShared = true)
        runCurrent()
        assertTrue(persisted.isEmpty())
        assertEquals(false, tabs.tabs.value.single().canPersist)
    }

    @Test
    fun aListedSessionGetsATabThatAttachesResumedWhenShown() = runTest {
        val tabs = tabs()
        tabs.take(listOf(hubView(ChannelTerminalSession("s1", account = "lab", isOwned = true, isPersistent = true))))
        assertEquals("s1", tabs.active.value)
        assertEquals(TerminalPhase.DETACHED, tabs.tabs.value.single().phase)
        assertEquals("lab", tabs.tabs.value.single().account)
        tabs.sized("s1", 80, 24)
        val (open, _) = shells.poll(5, TimeUnit.SECONDS) ?: error("no shell")
        assertEquals(true, open["is_resumed"]!!.jsonPrimitive.boolean)
        assertEquals("lab", open["account"]!!.jsonPrimitive.content)
        eventually { tabs.tabs.value.single().phase == TerminalPhase.OPEN }
    }

    @Test
    fun closingAKeptTabEndsItsSessionAndTheTabGoesOnceTheMachineAgrees() = runTest {
        val tabs = tabs()
        val (id, _) = opened(tabs)
        tabs.persist(id, isPersistent = true, isShared = false)
        tabs.close(id)
        runCurrent()
        assertEquals(listOf(id), stopped)
        assertTrue(tabs.tabs.value.isEmpty())
    }

    @Test
    fun aRefusedStopKeepsTheTabWithTheCode() = runTest {
        stopAnswer = ChannelResult.refused("session_not_owned", "session_id" to "s1")
        val tabs = tabs()
        val (id, _) = opened(tabs)
        tabs.persist(id, isPersistent = true, isShared = false)
        tabs.close(id)
        runCurrent()
        assertEquals("session_not_owned", tabs.tabs.value.single().note?.code)
    }

    @Test
    fun aClosedPlainTabStaysClosed() = runTest {
        val tabs = tabs()
        val (id, _) = opened(tabs)
        tabs.close(id)
        assertTrue(tabs.tabs.value.isEmpty())
        assertTrue(stopped.isEmpty())
        tabs.take(listOf(hubView(ChannelTerminalSession(id, isOwned = true))))
        assertTrue(tabs.tabs.value.isEmpty())
    }

    @Test
    fun aSessionTheMachineNoLongerKeepsEnds() = runTest {
        val tabs = tabs()
        val (_, end) = opened(tabs)
        val close = buildJsonObject {
            put("code", "session_unknown")
            put("params", JsonObject(emptyMap()))
        }
        TransportRecord.write(end.output, TRANSPORT_RECORD_CLOSE, close.toString().toByteArray())
        eventually { tabs.tabs.value.single().phase == TerminalPhase.ENDED }
        assertEquals("session_unknown", tabs.tabs.value.single().note?.code)
    }

    @Test
    fun aShellThatExitsEndsAPlainTab() = runTest {
        val tabs = tabs()
        val (_, end) = opened(tabs)
        TransportRecord.write(
            end.output,
            TRANSPORT_RECORD_CLOSE,
            """{"code":"","params":{"exit_code":0}}""".toByteArray(),
        )
        eventually { tabs.tabs.value.single().phase == TerminalPhase.ENDED }
    }

    @Test
    fun aStreamThatDropsLeavesTheTabDetached() = runTest {
        val tabs = tabs()
        val (_, end) = opened(tabs)
        end.close()
        eventually { tabs.tabs.value.single().phase == TerminalPhase.DETACHED }
    }

    @Test
    fun keysReachTheShellInTheOrderTyped() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        val keys = (0 until 200).map { "k$it;" }
        for (key in keys) tabs.input(id, key.toByteArray())
        val typed = StringBuilder()
        val input = DataInputStream(end.input)
        while (typed.length < keys.sumOf { it.length }) {
            val record = TransportRecord.read(input) ?: break
            if (record.type == TRANSPORT_RECORD_DATA) typed.append(String(record.payload))
        }
        assertEquals(keys.joinToString(""), typed.toString())
    }

    @Test
    fun clearSendsCtrlCAfterTheKeysBeforeIt() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        tabs.input(id, "yes".toByteArray())
        tabs.clear(id)
        val sent = records(end, 2).joinToString("") { String(it.payload) }
        assertEquals("yes\u0003", sent)
    }

    @Test
    fun clearDropsAFloodWholeAndDrawsTheFirstOutputAfterTheQuiet() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        val seen = StringBuffer()
        tabs.watch { _, bytes -> seen.append(String(bytes)) }
        output(end, "flood ")
        assertEquals("flood ", seen.toString())
        tabs.clear(id)
        repeat(20) {
            advanceTimeBy(100)
            output(end, "y ")
        }
        advanceTimeBy(CLIENT_TERMINAL_CLEAR_QUIET_MS - 1)
        output(end, "tail ")
        advanceTimeBy(CLIENT_TERMINAL_CLEAR_QUIET_MS)
        output(end, "$ ")
        assertEquals("flood $ ", seen.toString())
        val again = StringBuffer()
        tabs.watch { _, bytes -> again.append(String(bytes)) }
        assertEquals("$ ", again.toString())
    }

    @Test
    fun clearingEndsAtTheCap() = runTest {
        val tabs = tabs()
        val (id, end) = opened(tabs)
        tabs.watch { _, _ -> }
        tabs.clear(id)
        assertEquals(setOf(id), tabs.clearing.value)
        val stop = testScheduler.currentTime + CLIENT_TERMINAL_CLEAR_MAX_MS
        val step = CLIENT_TERMINAL_CLEAR_QUIET_MS / 2
        while (testScheduler.currentTime + step < stop) {
            advanceTimeBy(step)
            output(end, "y ")
        }
        assertEquals(setOf(id), tabs.clearing.value)
        advanceTimeBy(stop - testScheduler.currentTime)
        runCurrent()
        assertEquals(emptySet<String>(), tabs.clearing.value)
    }

    @Test
    fun aTabWithNoOpenShellRefusesTheClear() = runTest {
        val tabs = TerminalTabs({ null }, backgroundScope)
        val id = tabs.create("b1", "d1", "Argon")
        tabs.sized(id, 80, 24)
        assertEquals(false, tabs.clear(id))
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
