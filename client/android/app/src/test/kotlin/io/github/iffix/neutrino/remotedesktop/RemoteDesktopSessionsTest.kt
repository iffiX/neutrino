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
        sessions.connect("b1", "r1", "Neutrino:desk", "")
        sessions.connect("b1", "r1", "Neutrino:desk", "")
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
    fun theViewerOpensWithTheEntrysKeptChoice() = runTest {
        val kept = RemoteDesktopChoice(RemoteDesktopCodec.H264, RemoteDesktopQuality.LOW)
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.Ok(material) }, backgroundScope) { key ->
            if (key == "b1/r1") kept else RemoteDesktopChoice()
        }
        sessions.connect("b1", "r1", "x", "")
        runCurrent()
        assertEquals(kept, sessions.viewing.value?.second?.choice)
    }

    @Test
    fun theViewerOpensWithTheEntrysPlatform() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.Ok(material) }, backgroundScope)
        sessions.connect("b1", "r1", "x", "linux")
        runCurrent()
        assertEquals("linux", sessions.viewing.value?.second?.platformOs)
    }

    @Test
    fun aRefusedConnectWritesItsCodeUntilARefresh() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.refused("rdp_not_shared") }, backgroundScope)
        sessions.connect("b1", "r1", "x", "")
        runCurrent()
        assertEquals("rdp_not_shared", sessions.errors.value["b1/r1"]?.code)
        assertNull(sessions.viewing.value)
        sessions.clearErrors()
        assertEquals(emptyMap<String, ChannelResult.Refused>(), sessions.errors.value)
    }

    @Test
    fun theRowNamesTheAddressTheHubHandedBackOnceKnown() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.Ok(material) }, backgroundScope)
        assertNull(sessions.dialed.value["b1/r1"])
        sessions.connect("b1", "r1", "x", "")
        runCurrent()
        assertEquals("10.0.0.9:21118", sessions.dialed.value["b1/r1"])
        assertEquals("10.0.0.9", sessions.viewing.value?.second?.host)
        sessions.close()
        assertEquals("10.0.0.9:21118", sessions.dialed.value["b1/r1"])
        sessions.forget("b1")
        assertNull(sessions.dialed.value["b1/r1"])
    }

    @Test
    fun aRefusedConnectNamesNoAddress() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.refused("rdp_not_shared") }, backgroundScope)
        sessions.connect("b1", "r1", "x", "")
        runCurrent()
        assertNull(sessions.dialed.value["b1/r1"])
    }

    @Test
    fun leavingTheHubClosesItsViewer() = runTest {
        val sessions = RemoteDesktopSessions({ _, _ -> ChannelResult.Ok(material) }, backgroundScope)
        sessions.connect("b1", "r1", "x", "")
        runCurrent()
        sessions.forget("b2")
        assertEquals("b1/r1", sessions.viewing.value?.first)
        sessions.forget("b1")
        assertNull(sessions.viewing.value)
    }
}
