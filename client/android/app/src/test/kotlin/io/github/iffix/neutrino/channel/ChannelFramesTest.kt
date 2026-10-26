package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.PROTOCOL
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

class ChannelFramesTest {
    private fun assertConforms(frame: JsonObject, model: String, hasType: Boolean = true) {
        if (hasType) assertEquals(true, frame["type"] is JsonPrimitive)
        val body = JsonObject(frame - "type")
        assertEquals(emptyList<String>(), GoldenSchema.problems(body, model))
    }

    @Test
    fun theProtocolIsTheGoldens() {
        assertEquals(GoldenSchema.protocol, PROTOCOL)
    }

    @Test
    fun helloIsTheGoldensHelloWithEveryFieldAndNoToken() {
        val hello = ChannelFrames.hello(Samples.binding, Samples.machine)
        assertConforms(hello, "ChannelHello")
        assertEquals(GoldenSchema.properties("ChannelHello"), hello.keys - "type")
        assertEquals("hello", hello["type"]!!.jsonPrimitive.content)
        assertEquals(PROTOCOL, hello["protocol"]!!.jsonPrimitive.int)
        assertEquals("client", hello["role"]!!.jsonPrimitive.content)
        assertEquals("neutrino_client/0.6.0", hello["software"]!!.jsonPrimitive.content)
        assertEquals(null, hello["token"])
    }

    @Test
    fun reportIsTheGoldensClientReportWithEveryField() {
        val report = ChannelFrames.report("h1", Samples.machine)
        assertConforms(report, "ChannelClientReport")
        assertEquals(GoldenSchema.properties("ChannelClientReport"), report.keys - "type")
        val machine = report["machine"] as JsonObject
        assertEquals(GoldenSchema.properties("ChannelClientMachine"), machine.keys)
    }

    @Test
    fun aRefreshReportSaysSo() {
        assertEquals(
            true,
            ChannelFrames.report("h1", Samples.machine, isRefresh = true)["is_refresh"]!!.jsonPrimitive.boolean,
        )
        assertEquals(false, ChannelFrames.report("h1", Samples.machine)["is_refresh"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun reportCarriesThePlatformsThreeKeys() {
        val platform = (ChannelFrames.report("", Samples.machine)["machine"] as JsonObject)["platform"] as JsonObject
        assertEquals(setOf("os", "family", "arch"), platform.keys)
        assertEquals("android", platform["os"]!!.jsonPrimitive.content)
    }

    @Test
    fun pingIsTheGoldensPingWithEveryField() {
        val ping = ChannelFrames.ping("n7")
        assertConforms(ping, "ChannelPing")
        assertEquals(GoldenSchema.properties("ChannelPing"), ping.keys - "type")
        assertEquals("ping", ping["type"]!!.jsonPrimitive.content)
        assertEquals("n7", ping["nonce"]!!.jsonPrimitive.content)
    }

    @Test
    fun serviceIsTheGoldensServiceForAnEntryAndForThePanel() {
        val entry = ChannelFrames.service("r1", ChannelFrames.args("id" to "rdp_d1"))
        assertConforms(entry, "ChannelService")
        assertEquals("service", entry["type"]!!.jsonPrimitive.content)
        val panel = ChannelFrames.service("r2", ChannelFrames.args("is_panel" to true))
        assertConforms(panel, "ChannelService")
    }

    @Test
    fun persistAndStopSessionAreTheGoldensWithEveryField() {
        val persist = ChannelFrames.persist("r1", "s1", isPersistent = true, isShared = false)
        assertConforms(persist, "ChannelPersist")
        assertEquals(GoldenSchema.properties("ChannelPersist"), persist.keys - "type")
        val stop = ChannelFrames.stopSession("r2", "s1")
        assertConforms(stop, "ChannelStopSession")
        assertEquals(GoldenSchema.properties("ChannelStopSession"), stop.keys - "type")
    }

    @Test
    fun theJoinBodyIsTheGoldensJoinWithEveryField() {
        val body = ChannelFrames.join("ticket", Samples.machine)
        assertConforms(body, "ChannelJoin", hasType = false)
        assertEquals(GoldenSchema.properties("ChannelJoin"), body.keys)
    }

    @Test
    fun aValueTheGoldenRefusesIsCaught() {
        val broken = JsonObject(ChannelFrames.ping("n") + ("nonce" to JsonPrimitive(7)))
        assertEquals(1, GoldenSchema.problems(JsonObject(broken - "type"), "ChannelPing").size)
    }
}
