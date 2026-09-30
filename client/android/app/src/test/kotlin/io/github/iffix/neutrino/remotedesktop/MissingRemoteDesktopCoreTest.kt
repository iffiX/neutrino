package io.github.iffix.neutrino.remotedesktop

import android.graphics.SurfaceTexture
import android.view.Surface
import io.github.iffix.neutrino.channel.ChannelResult
import org.junit.Assert.assertEquals
import org.junit.Test

class MissingRemoteDesktopCoreTest {
    @Test
    fun aConnectionStopsAtOnceSayingNoCoreIsBuiltIn() {
        val states = mutableListOf<RemoteDesktopState>()
        MissingRemoteDesktopCore().connect(RemoteDesktopTarget("a", "h", 1, "p"), Surface(SurfaceTexture(0))) {
            states += it
        }
        assertEquals(listOf(RemoteDesktopState.Stopped(ChannelResult.refused("rdp_core_missing"))), states)
    }
}
