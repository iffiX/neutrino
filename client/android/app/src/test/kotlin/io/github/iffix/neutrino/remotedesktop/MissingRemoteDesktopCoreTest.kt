package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.channel.ChannelResult
import org.junit.Assert.assertEquals
import org.junit.Test

class MissingRemoteDesktopCoreTest {
    @Test
    fun aConnectionStopsAtOnceSayingNoCoreIsBuiltIn() {
        val states = mutableListOf<RemoteDesktopState>()
        MissingRemoteDesktopCore().connect(RemoteDesktopTarget("a", "h", 1, "p"), { states += it }, { _, _ -> }, {})
        assertEquals(listOf(RemoteDesktopState.Stopped(ChannelResult.refused("rdp_core_missing"))), states)
    }
}
