package io.github.iffix.neutrino.binding

import io.github.iffix.neutrino.channel.Samples
import org.junit.Assert.assertEquals
import org.junit.Test

class HubBindingTest {
    @Test
    fun candidateUrlsAreTheNameThenTheLastThenTheRestEachOnce() {
        val binding = Samples.binding.copy(gatewayUrl = "https://100.72.4.1:8443")
        assertEquals(
            listOf("https://10.0.0.1:8443", "https://100.72.4.1:8443", "https://192.168.100.1:8443"),
            binding.candidateUrls("https://10.0.0.1:8443"),
        )
        assertEquals(listOf("https://100.72.4.1:8443", "https://192.168.100.1:8443"), binding.candidateUrls(""))
    }

    @Test
    fun theLastAddressIsStoredWhenTheListLacksIt() {
        val binding = Samples.binding.copy(gatewayUrl = "https://10.0.0.1:8443")
        assertEquals(Samples.binding.gatewayUrls + "https://10.0.0.1:8443", binding.storedUrls)
    }

    @Test
    fun theTitleIsTheHubsNameElseItsAddress() {
        assertEquals("https://192.168.100.1:8443", Samples.binding.title)
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
