package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class RemoteDesktopSessionsTest {
    private val material = JsonObject(mapOf("password" to JsonPrimitive("p")))
    private val held = mutableListOf<Triple<String, String, Int>>()
    private val released = mutableListOf<Pair<String, String>>()
    private var bound: ChannelResult<Int> = ChannelResult.Ok(31118)

    private fun sessions(
        scope: CoroutineScope,
        answer: suspend (String, String) -> ChannelResult<JsonObject> = { _, _ -> ChannelResult.Ok(material) },
        choiceOf: (String) -> RemoteDesktopChoice = { RemoteDesktopChoice() },
    ) = RemoteDesktopSessions(
        answer,
        forward = { bindingId, entryId, port ->
            held += Triple(bindingId, entryId, port)
            bound
        },
        release = { bindingId, entryId -> released += bindingId to entryId },
        scope = scope,
        choiceOf = choiceOf,
    )

    @Test
    fun connectIsAJobUntilTheViewerOpensOnTheForward() = runTest {
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        var asked = 0
        val sessions = sessions(backgroundScope, { _, _ ->
            asked += 1
            answer.await()
        })
        sessions.connect("b1", "r1", "Neutrino:desk", "", 21118)
        sessions.connect("b1", "r1", "Neutrino:desk", "", 21118)
        runCurrent()
        assertEquals(setOf("b1/r1"), sessions.connecting.value)
        assertEquals(1, asked)
        answer.complete(ChannelResult.Ok(material))
        runCurrent()
        assertEquals(emptySet<String>(), sessions.connecting.value)
        assertEquals(listOf(Triple("b1", "r1", 21118)), held)
        val target = sessions.viewing.value?.second
        assertEquals("b1/r1", sessions.viewing.value?.first)
        assertEquals("127.0.0.1", target?.host)
        assertEquals(31118, target?.port)
        assertEquals("p", target?.password)
    }

    @Test
    fun theViewerOpensWithTheEntrysKeptChoiceAndPlatform() = runTest {
        val kept = RemoteDesktopChoice(RemoteDesktopCodec.H264, RemoteDesktopQuality.LOW)
        val sessions = sessions(backgroundScope, choiceOf = { key ->
            if (key ==
                "b1/r1"
            ) {
                kept
            } else {
                RemoteDesktopChoice()
            }
        })
        sessions.connect("b1", "r1", "x", "linux", 21118)
        runCurrent()
        assertEquals(kept, sessions.viewing.value?.second?.choice)
        assertEquals("linux", sessions.viewing.value?.second?.platformOs)
    }

    @Test
    fun aRefusedConnectWritesItsCodeAndMakesNoForward() = runTest {
        val sessions = sessions(backgroundScope, { _, _ -> ChannelResult.refused("rdp_not_shared") })
        sessions.connect("b1", "r1", "x", "", 21118)
        runCurrent()
        assertEquals("rdp_not_shared", sessions.errors.value["b1/r1"]?.code)
        assertNull(sessions.viewing.value)
        assertTrue(held.isEmpty())
        sessions.clearErrors()
        assertEquals(emptyMap<String, ChannelResult.Refused>(), sessions.errors.value)
    }

    @Test
    fun aForwardThatFailsWritesItsCode() = runTest {
        bound = ChannelResult.refused("forward_failed", "detail" to "no local port is free")
        val sessions = sessions(backgroundScope)
        sessions.connect("b1", "r1", "x", "", 21118)
        runCurrent()
        assertEquals("forward_failed", sessions.errors.value["b1/r1"]?.code)
        assertNull(sessions.viewing.value)
    }

    @Test
    fun closingTheViewerEndsTheForward() = runTest {
        val sessions = sessions(backgroundScope)
        sessions.connect("b1", "r1", "x", "", 21118)
        runCurrent()
        sessions.close()
        assertNull(sessions.viewing.value)
        assertEquals(listOf("b1" to "r1"), released)
        sessions.close()
        assertEquals(1, released.size)
    }

    @Test
    fun leavingTheHubClosesItsViewer() = runTest {
        val sessions = sessions(backgroundScope)
        sessions.connect("b1", "r1", "x", "", 21118)
        runCurrent()
        sessions.forget("b2")
        assertEquals("b1/r1", sessions.viewing.value?.first)
        sessions.forget("b1")
        assertNull(sessions.viewing.value)
        assertEquals(listOf("b1" to "r1"), released)
    }
}
