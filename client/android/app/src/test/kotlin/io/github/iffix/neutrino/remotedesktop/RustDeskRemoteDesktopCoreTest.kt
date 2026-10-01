package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_STATE_CLOSED
import io.github.iffix.neutrino.RDP_STATE_CONNECTED
import io.github.iffix.neutrino.RDP_STATE_LOGIN_FAILED
import io.github.iffix.neutrino.RepositoryFiles
import io.github.iffix.neutrino.channel.ChannelResult
import org.junit.Assert.assertEquals
import org.junit.Test

class RustDeskRemoteDesktopCoreTest {
    private val connecting = RemoteDesktopState.Connecting

    @Test
    fun aLoginShowsThePicture() {
        assertEquals(RemoteDesktopState.Showing, RustDeskRemoteDesktopCore.next(connecting, RDP_STATE_CONNECTED, ""))
    }

    @Test
    fun aRefusedPasswordStopsWithItsOwnCode() {
        assertEquals(
            RemoteDesktopState.Stopped(ChannelResult.refused("rdp_login_failed")),
            RustDeskRemoteDesktopCore.next(connecting, RDP_STATE_LOGIN_FAILED, "Wrong Password"),
        )
    }

    @Test
    fun anEndedConnectionStopsWithRustDesksReason() {
        val shown = RustDeskRemoteDesktopCore.next(connecting, RDP_STATE_CONNECTED, "")
        assertEquals(
            RemoteDesktopState.Stopped(ChannelResult.refused("rdp_closed", "reason" to "Reset by the peer")),
            RustDeskRemoteDesktopCore.next(shown, RDP_STATE_CLOSED, "Reset by the peer"),
        )
    }

    @Test
    fun aStoppedConnectionStaysStopped() {
        val stopped = RustDeskRemoteDesktopCore.next(connecting, RDP_STATE_LOGIN_FAILED, "")
        assertEquals(stopped, RustDeskRemoteDesktopCore.next(stopped, RDP_STATE_CLOSED, "Connection closed"))
        assertEquals(stopped, RustDeskRemoteDesktopCore.next(stopped, RDP_STATE_CONNECTED, ""))
    }

    @Test
    fun anUnknownReportChangesNothing() {
        assertEquals(connecting, RustDeskRemoteDesktopCore.next(connecting, 99, ""))
    }

    @Test
    fun theStatesAreTheOnesThePatchExports() {
        val patch = RepositoryFiles.text("packaging/build/build_core_rustdesk.patch")
        for ((name, value) in listOf(
            "ND_STATE_CONNECTED" to RDP_STATE_CONNECTED,
            "ND_STATE_LOGIN_FAILED" to RDP_STATE_LOGIN_FAILED,
            "ND_STATE_CLOSED" to RDP_STATE_CLOSED,
        )) {
            val pinned = Regex("""pub const $name: c_int = (\d+);""").find(patch)?.groupValues?.get(1)?.toInt()
            assertEquals(name, value, pinned)
        }
    }
}
