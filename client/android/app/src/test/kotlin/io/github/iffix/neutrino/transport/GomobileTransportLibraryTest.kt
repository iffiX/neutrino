package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_LIBRARY_CLASS
import io.github.iffix.neutrino.TransportMissingException
import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Test

class GomobileTransportLibraryTest {
    @Test
    fun theLibraryIsTheClassBoundIntoNetBirdsAar() {
        assertEquals("io.netbird.gomobile.mobile.Mobile", TRANSPORT_LIBRARY_CLASS)
    }

    @Test(expected = TransportMissingException::class)
    fun aBuildWithoutTheLibrarySaysSoAtTheStart() {
        GomobileTransportLibrary("io.netbird.gomobile.mobile.Missing").start("/data", "aa".repeat(32))
    }

    @Test
    fun startReturnsTheSocketTheLibraryBound() {
        assertEquals("/data/transport.sock", GomobileTransportLibrary(Bound::class.java.name).start("/data", "s"))
    }

    @Test(expected = IOException::class)
    fun aLibraryThatFailsToStartIsAnIoFailure() {
        GomobileTransportLibrary(Failing::class.java.name).start("/data", "s")
    }

    @Test
    fun stoppingAMissingLibraryDoesNothing() {
        GomobileTransportLibrary("io.netbird.gomobile.mobile.Missing").stop()
    }

    /** Stands in for the bound class: static `start` and `stop`. */
    object Bound {
        @JvmStatic
        fun start(directory: String, secret: String): String = "$directory/transport.sock".also { secret.length }

        @JvmStatic
        fun stop() = Unit
    }

    /** Stands in for a bound class whose start fails, as gomobile throws a Go error. */
    object Failing {
        @JvmStatic
        fun start(directory: String, secret: String): String = throw IllegalStateException("bind: $directory $secret")

        @JvmStatic
        fun stop() = Unit
    }
}
