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
    fun helloIsTheGoldensHelloWithEveryField() {
        val hello = ChannelFrames.hello(Samples.binding, Samples.machine)
        assertConforms(hello, "ChannelHello")
        assertEquals(GoldenSchema.properties("ChannelHello"), hello.keys - "type")
        assertEquals("hello", hello["type"]!!.jsonPrimitive.content)
        assertEquals(PROTOCOL, hello["protocol"]!!.jsonPrimitive.int)
        assertEquals("client", hello["role"]!!.jsonPrimitive.content)
        assertEquals("neutrino_client/0.5.0", hello["software"]!!.jsonPrimitive.content)
        assertEquals("secret-token", hello["token"]!!.jsonPrimitive.content)
    }

    @Test
    fun reportIsTheGoldensClientReport() {
        val report = ChannelFrames.report("h1", Samples.machine)
        assertConforms(report, "ChannelClientReport")
        assertEquals(GoldenSchema.properties("ChannelClientReport"), report.keys - "type")
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
    fun reportCarriesThePlatformTuple() {
        val platform = (ChannelFrames.report("", Samples.machine)["machine"] as JsonObject)["platform"] as JsonObject
        assertEquals(setOf("os", "family", "arch", "version"), platform.keys)
        assertEquals("android", platform["os"]!!.jsonPrimitive.content)
    }

    @Test
    fun openIsTheGoldensOpenWithItsArgumentsBeside() {
        val open = ChannelFrames.open(3, "service", ChannelFrames.args("id" to "svc"))
        assertConforms(open, "ChannelOpen")
        assertEquals("svc", open["id"]!!.jsonPrimitive.content)
    }

    @Test
    fun closeIsTheGoldensClose() {
        assertConforms(ChannelFrames.close(2, "kind_unknown"), "ChannelClose")
        assertConforms(ChannelFrames.close(5), "ChannelClose")
    }

    @Test
    fun creditIsTheGoldensCredit() {
        assertConforms(ChannelFrames.credit(1, 1024), "ChannelCredit")
    }

    @Test
    fun theJoinBodyIsTheGoldensJoinRequestWithEveryField() {
        val body = ChannelFrames.joinRequest("ticket", Samples.machine)
        assertConforms(body, "ChannelJoinRequest", hasType = false)
        assertEquals(GoldenSchema.properties("ChannelJoinRequest"), body.keys)
    }

    @Test
    fun theLeaveBodyIsTheGoldensLeaveRequest() {
        val body = ChannelFrames.leaveRequest(Samples.binding)
        assertConforms(body, "ChannelLeaveRequest", hasType = false)
        assertEquals(GoldenSchema.properties("ChannelLeaveRequest"), body.keys)
    }

    @Test
    fun aValueTheGoldenRefusesIsCaught() {
        val broken = JsonObject(ChannelFrames.credit(1, 1) + ("bytes" to JsonPrimitive("many")))
        assertEquals(1, GoldenSchema.problems(JsonObject(broken - "type"), "ChannelCredit").size)
    }
}
