package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class RemoteDesktopSessionsTest {
    private val material = JsonObject(
        mapOf("host" to JsonPrimitive("10.0.0.9"), "port" to JsonPrimitive(21118), "password" to JsonPrimitive("p")),
    )

    @Test
    fun connectIsAJobUntilTheViewerOpens() = runTest {
        val answer = CompletableDeferred<ChannelResult<JsonObject>>()
        var asked = 0
        val sessions = RemoteDesktopSessions({ _, _ ->
            asked += 1
            answer.await()
        }, backgroundScope)
        sessions.connect("b1", "r1", "Neutrino:desk")
        sessions.connect("b1", "r1", "Neutrino:desk")
        runCurrent()
        assertEquals(setOf("b1/r1"), sessions.connecting.value)
        assertEquals(1, asked)
        answer.complete(ChannelResult.Ok(material))
        runCurrent()
        assertEquals(emptySet<String>(), sessions.connecting.value)
        assertEquals("b1/r1", sessions.viewing.value?.first)
        assertEquals(21118, sessions.viewing.value?.second?.port)
    }

    @Test
    fun aRefusedConnectWritesItsCodeUntilARefresh() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.refused("rdp_not_shared") }, backgroundScope)
        sessions.connect("b1", "r1", "x")
        runCurrent()
        assertEquals("rdp_not_shared", sessions.errors.value["b1/r1"]?.code)
        assertNull(sessions.viewing.value)
        sessions.clearErrors()
        assertEquals(emptyMap<String, ChannelResult.Refused>(), sessions.errors.value)
    }

    @Test
    fun leavingTheHubClosesItsViewer() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.Ok(material) }, backgroundScope)
        sessions.connect("b1", "r1", "x")
        runCurrent()
        sessions.forget("b2")
        assertEquals("b1/r1", sessions.viewing.value?.first)
        sessions.forget("b1")
        assertNull(sessions.viewing.value)
    }
}
