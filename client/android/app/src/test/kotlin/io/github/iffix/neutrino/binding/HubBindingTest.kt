package io.github.iffix.neutrino.binding

import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Test

class HubBindingTest {
    @Test
    fun thePskIsTheSha256OfTheTokenInHex() {
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest("secret-token".toByteArray())
        assertEquals(digest.joinToString("") { "%02x".format(it) }, Samples.binding.psk)
    }

    @Test
    fun noHubKeyIsAnOldBinding() {
        assertEquals(false, Samples.binding.isKeyMissing)
        assertEquals(true, Samples.binding.copy(hubKey = "").isKeyMissing)
    }

    @Test
    fun theLastAddressIsStoredWhenTheListLacksIt() {
        val binding = Samples.binding.copy(gatewayUrl = "tcp://10.0.0.1:8443")
        assertEquals(Samples.binding.gatewayUrls + "tcp://10.0.0.1:8443", binding.storedUrls)
    }

    @Test
    fun theTitleIsTheHubsNameElseItsAddress() {
        assertEquals("tcp://192.168.100.1:8443", Samples.binding.title)
        assertEquals("Neutrino", Samples.binding.copy(hubName = "Neutrino").title)
    }

    @Test
    fun aBindingWithATicketIsPendingAndTheHubKnowsItByItsOwnIdOnceSpent() {
        val pending = Samples.binding.copy(token = "", ticket = "ticket-1")
        assertEquals(true, pending.isPending)
        assertEquals(false, Samples.binding.isPending)
        assertEquals("b1", Samples.binding.boundId)
        assertEquals("c9", pending.copy(ticket = "", hubBindingId = "c9").boundId)
    }
}
