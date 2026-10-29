package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.GoldenSchema
import io.github.iffix.neutrino.binding.BindingStore
import io.github.iffix.neutrino.binding.FakeSecretSealer
import io.github.iffix.neutrino.binding.HubBinding
import io.github.iffix.neutrino.transport.ClientTransport
import io.github.iffix.neutrino.transport.FakeTransport
import java.net.InetAddress
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class HubSessionTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val fake = FakeTransport()
    private val transport = ClientTransport(fake, "/data", { fake }, scope, log = {}).also { it.start() }
    private val joined = mutableListOf<Pair<String, String>>()
    private val nanos = AtomicLong(0)
    private val lanUrl = "tcp://192.168.100.1:8443"
    private val directUrl = "tcp://100.72.4.1:8443"
    private val lanNetwork = ChannelLocalNetwork(InetAddress.getByName("192.168.100.7"), 24)

    @After
    fun end() {
        scope.cancel()
    }

    private fun session(
        binding: HubBinding = Samples.binding,
        nameAddress: String? = null,
        hasNetwork: () -> Boolean = { true },
        onWelcomed: (String, String) -> Unit = { _, _ -> },
    ): Pair<HubSession, BindingStore> {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(binding)
        val session = HubSession(
            "b1",
            store,
            transport,
            Samples.machine,
            { nameAddress },
            { id, hubId -> joined += id to hubId },
            onWelcomed = onWelcomed,
            clock = { CLOCK_MILLIS },
            localNetworks = { listOf(lanNetwork) },
            nanoClock = { nanos.get() },
            hasNetwork = hasNetwork,
        )
        session.start(scope)
        return session to store
    }

    private fun eventually(what: String, check: () -> Boolean) {
        val until = System.currentTimeMillis() + 5000
        while (System.currentTimeMillis() < until) {
            if (check()) return
            Thread.sleep(10)
        }
        throw AssertionError("never: $what")
    }

    private fun welcome() = buildJsonObject {
        put("type", "welcome")
        put("protocol", 4)
        put("role", "hub")
        put("id", "hub-1")
        put("name", "Neutrino")
        put("software", "neutrino_hub/0.6.0")
        put("time", 1.5)
    }

    private fun connected(session: HubSession, isDialled: Boolean = false): JsonObject {
        val dial = if (isDialled) JsonObject(emptyMap()) else fake.nextCommand("dial") ?: error("no dial")
        fake.event("session_open", "b1", "address" to lanUrl, "path" to "lan", "handshake_ms" to 4)
        val hello = fake.nextFrame("hello")?.second ?: error("no hello")
        fake.frame("b1", welcome())
        eventually("connected") { session.view.value.isConnected }
        assertTrue(hello.isNotEmpty())
        return dial
    }

    @Test
    fun aBoundBindingDialsEveryCandidateWithItsPathKeyAndPsk() {
        session(nameAddress = "192.168.100.1")
        val dial = fake.nextCommand("dial") ?: error("no dial")
        assertEquals("b1", FakeTransport.text(dial, "binding"))
        assertEquals(Samples.HUB_KEY, FakeTransport.text(dial, "hub_key"))
        assertEquals(Samples.PRIVATE_KEY, FakeTransport.text(dial, "private_key"))
        val digest = MessageDigest.getInstance("SHA-256").digest("secret-token".toByteArray())
        assertEquals(digest.joinToString("") { "%02x".format(it) }, FakeTransport.text(dial, "psk"))
        assertEquals("client", FakeTransport.text(dial, "role"))
        assertEquals(4, dial["protocol"]!!.jsonPrimitive.content.toInt())
        val candidates = (dial["candidates"] as JsonArray).map {
            it.jsonObject["address"]!!.jsonPrimitive.content to it.jsonObject["path"]!!.jsonPrimitive.content
        }
        assertEquals(listOf(lanUrl to "lan", directUrl to "direct"), candidates)
    }

    @Test
    fun aSessionIsGreetedWithAHelloOfNoTokenAndTheWelcomeConnectsIt() {
        val seen = mutableListOf<Pair<String, String>>()
        val (session, store) = session { id, hubId -> seen += id to hubId }
        fake.nextCommand("dial")
        fake.event("session_open", "b1", "address" to lanUrl, "path" to "lan", "handshake_ms" to 4)
        val (binding, hello) = fake.nextFrame("hello") ?: error("no hello")
        assertEquals("b1", binding)
        assertEquals(emptyList<String>(), GoldenSchema.problems(JsonObject(hello - "type"), "ChannelHello"))
        assertEquals(GoldenSchema.properties("ChannelHello"), hello.keys - "type")
        fake.frame("b1", welcome())
        eventually("connected") { session.view.value.isConnected }
        assertEquals(listOf("b1" to "hub-1"), seen)
        assertEquals("hub-1", store.get("b1")?.hubId)
        assertEquals("Neutrino", store.get("b1")?.hubName)
        assertEquals(lanUrl, store.get("b1")?.gatewayUrl)
        assertEquals("neutrino_hub/0.6.0", session.view.value.software)
        val report = fake.nextFrame("report")?.second ?: error("no report")
        assertEquals(emptyList<String>(), GoldenSchema.problems(JsonObject(report - "type"), "ChannelClientReport"))
        assertTrue(fake.nextFrame("ping") != null)
    }

    @Test
    fun thePongOfTheLastPingSetsTheRoundTripAndAnyOtherIsDropped() {
        val (session, _) = session()
        connected(session)
        val ping = fake.nextFrame("ping")?.second ?: error("no ping")
        nanos.set(7_000_000)
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "pong")
                put("nonce", "another")
            },
        )
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "pong")
                put("nonce", ping["nonce"]!!.jsonPrimitive.content)
            },
        )
        eventually("rtt") { session.view.value.rttMs == 7L }
    }

    @Test
    fun aStateIsTakenAndAnsweredWithItsHash() {
        val (session, store) = session()
        connected(session)
        fake.nextFrame("report")
        fake.frame("b1", Json.state())
        eventually("apps") { session.view.value.apps.isNotEmpty() }
        val view = session.view.value
        assertEquals(listOf("gitea_d1"), view.apps.map { it.id })
        assertEquals(27311, view.services.single().localPort)
        assertEquals("gitea_d1", view.services.single().appId)
        assertEquals(listOf("iffi", "lab"), view.terminals.single().accounts)
        assertEquals("lan", view.reachedThrough)
        assertEquals(listOf(lanUrl), store.get("b1")?.gatewayUrls)
        val report = fake.nextFrame("report")?.second ?: error("no report")
        assertEquals("h9", report["state_hash"]!!.jsonPrimitive.content)
    }

    @Test
    fun aServiceFrameIsAnsweredByTheReplyOfItsRequest() {
        val (session, _) = session()
        connected(session)
        val asked = scope.async { session.openService("rdp_d1") }
        val (_, service) = fake.nextFrame("service") ?: error("no service")
        assertEquals(emptyList<String>(), GoldenSchema.problems(JsonObject(service - "type"), "ChannelService"))
        assertEquals("rdp_d1", service["id"]!!.jsonPrimitive.content)
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "reply")
                put("request", service["request"]!!)
                put("code", "")
                put("params", buildJsonObject { put("password", "seat") })
            },
        )
        val answer = runBlocking { asked.await() }
        assertEquals("seat", (answer as ChannelResult.Ok).value["password"]!!.jsonPrimitive.content)
    }

    @Test
    fun aRefusedReplyIsItsCode() {
        val (session, _) = session()
        connected(session)
        val asked = scope.async { session.persist("s1", isPersistent = true, isShared = false) }
        val (_, persist) = fake.nextFrame("persist") ?: error("no persist")
        assertEquals(emptyList<String>(), GoldenSchema.problems(JsonObject(persist - "type"), "ChannelPersist"))
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "reply")
                put("request", persist["request"]!!)
                put("code", "session_not_owned")
                put("params", buildJsonObject { put("session_id", "s1") })
            },
        )
        assertEquals("session_not_owned", (runBlocking { asked.await() } as ChannelResult.Refused).code)
    }

    @Test
    fun aRoundThatEndsWithNoSessionWaitsTheSecondsTheTransportNames() {
        val (session, _) = session()
        fake.nextCommand("dial")
        fake.event("round_end", "b1", "code" to "hub_unreachable", "next_round_s" to 10)
        eventually("waiting") { session.view.value.waitReason == HubWaitReason.HUB_SILENT }
        assertEquals(CLOCK_MILLIS + 10_000, session.view.value.nextRoundAtMillis)
    }

    @Test
    fun aRunOfControlUnavailableRefusalsWritesFourLines() {
        val store = BindingStore(folder.root.resolve("b.sealed"), FakeSecretSealer())
        store.put(Samples.binding)
        val now = AtomicLong(CLOCK_MILLIS)
        val lines = CopyOnWriteArrayList<String>()
        val session = HubSession(
            "b1",
            store,
            transport,
            Samples.machine,
            { null },
            clock = { now.get() },
            localNetworks = { listOf(lanNetwork) },
            nanoClock = { nanos.get() },
            writeLog = { lines += it },
        )
        session.start(scope)
        fake.nextCommand("dial")
        for (turn in 0 until 30) {
            now.set(CLOCK_MILLIS + turn * 5_000L)
            fake.event("round_end", "b1", "code" to "control_unavailable", "next_round_s" to 5)
            eventually("refusal $turn") { session.view.value.nextRoundAtMillis == now.get() + 5_000 }
        }
        connected(session, isDialled = true)
        val title = Samples.binding.title
        assertEquals(
            listOf(
                "hub $title: waiting on hub_silent for 5s: control_unavailable",
                "hub $title: waiting on hub_silent for 5s: control_unavailable, 12 times since the last line",
                "hub $title: waiting on hub_silent for 5s: control_unavailable, 12 times since the last line",
                "hub $title: the hub welcomed this client; refused control_unavailable 5 times since the last line",
            ),
            lines.filter { "control_unavailable" in it },
        )
    }

    @Test
    fun aKeyThatOpensUnderNoPskIsAMismatch() {
        val (session, _) = session()
        fake.nextCommand("dial")
        fake.event("round_end", "b1", "code" to "hub_untrusted", "next_round_s" to 60)
        eventually("untrusted") { session.view.value.waitReason == HubWaitReason.UNTRUSTED }
    }

    @Test
    fun aRoundWithNoNetworkWaitsForTheNetwork() {
        val (session, _) = session(hasNetwork = { false })
        fake.nextCommand("dial")
        fake.event("round_end", "b1", "code" to "hub_unreachable", "next_round_s" to 5)
        eventually("no network") { session.view.value.waitReason == HubWaitReason.NO_NETWORK }
        assertEquals(0L, session.view.value.nextRoundAtMillis)
    }

    @Test
    fun aSessionAnotherClientTookWaitsForReconnectWhichDialsAgain() {
        val (session, _) = session()
        connected(session)
        fake.event("session_end", "b1", "code" to "replaced", "params" to JsonObject(emptyMap()))
        eventually("replaced") { session.view.value.waitReason == HubWaitReason.REPLACED }
        assertTrue(!session.refresh())
        session.reconnect()
        assertTrue(fake.nextCommand("dial") != null)
    }

    @Test
    fun aBindingTheHubForgotWaitsForLeave() {
        val (session, _) = session()
        fake.nextCommand("dial")
        fake.event("round_end", "b1", "code" to "binding_unknown", "next_round_s" to 0)
        eventually("unknown") { session.view.value.waitReason == HubWaitReason.UNKNOWN_DEVICE }
        assertTrue(session.view.value.isLeaveOnly)
    }

    @Test
    fun aSessionThatDropsIsDialledAgainByTheTransportAndReadsConnecting() {
        val (session, _) = session()
        connected(session)
        fake.event("session_end", "b1")
        eventually("connecting") { session.view.value.connection == HubConnection.CONNECTING }
        assertNull(session.view.value.rttMs)
        assertTrue(session.view.value.droppedAtMillis > 0)
    }

    @Test
    fun aMoveGreetsTheNewSessionAndStaysConnected() {
        val (session, _) = session()
        connected(session)
        fake.event("session_open", "b1", "address" to directUrl, "path" to "direct", "handshake_ms" to 2)
        assertTrue(fake.nextFrame("hello") != null)
        fake.frame("b1", welcome())
        eventually("moved") { session.view.value.connectedAddress == directUrl }
        assertTrue(session.view.value.isConnected)
    }

    @Test
    fun aDisabledStateKeepsTheSessionAndWaits() {
        val (session, _) = session()
        connected(session)
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "state")
                put("hash", "h1")
                put("is_disabled", true)
            },
        )
        eventually("disabled") { session.view.value.isDisabled }
    }

    @Test
    fun aRefreshReportsWithIsRefreshWhileConnectedAndStartsARoundOtherwise() {
        val (session, _) = session()
        fake.nextCommand("dial")
        assertTrue(session.refresh())
        assertTrue(fake.nextCommand("round") != null)
        session.view.value.let { assertTrue(it.jobs.isRefreshing) }
        connected(session, isDialled = true)
        fake.frame(
            "b1",
            buildJsonObject {
                put("type", "state")
                put("hash", "h1")
            },
        )
        eventually("refresh ends") { !session.view.value.jobs.isRefreshing }
        fake.frames.clear()
        assertTrue(session.refresh())
        val reports = generateSequence { fake.nextFrame("report")?.second }
        assertTrue(reports.any { it["is_refresh"]!!.jsonPrimitive.content.toBoolean() })
    }

    @Test
    fun aNetworkChangeStartsARound() {
        val (session, _) = session()
        fake.nextCommand("dial")
        session.networkChanged()
        assertTrue(fake.nextCommand("round") != null)
    }

    @Test
    fun aPendingBindingSpendsItsTicketWithTheTransportsJoinThenDials() {
        val pending = Samples.binding.copy(token = "", ticket = "ticket-1")
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("binding_id", "c9")
                    put("token", "t9")
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val (_, store) = session(binding = pending)
        val join = fake.nextCommand("join") ?: error("no join")
        val body = JsonObject(join.filterKeys { it in GoldenSchema.properties("ChannelJoin") })
        assertEquals(emptyList<String>(), GoldenSchema.problems(body, "ChannelJoin"))
        assertEquals("ticket-1", FakeTransport.text(join, "ticket"))
        assertEquals(Samples.HUB_KEY, FakeTransport.text(join, "hub_key"))
        assertEquals(JsonArray(listOf(JsonPrimitive(lanUrl), JsonPrimitive(directUrl))), join["addresses"])
        assertTrue(fake.nextCommand("dial") != null)
        assertEquals("t9", store.get("b1")?.token)
        assertEquals("c9", store.get("b1")?.boundId)
        assertEquals("", store.get("b1")?.ticket)
        assertEquals(listOf("b1" to "c9"), joined)
    }

    @Test
    fun aRefusedTicketEndsTheJoinWithNoRound() {
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("code", "ticket_spent")
                    put("params", JsonObject(emptyMap()))
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val (session, _) = session(binding = Samples.binding.copy(token = "", ticket = "ticket-1"))
        eventually("refused") { session.view.value.waitReason == HubWaitReason.JOIN_REFUSED }
        assertEquals("ticket_spent", session.view.value.waitRefusal?.code)
        assertNull(fake.nextCommand("dial", seconds = 1))
    }

    @Test
    fun aPausedAdmissionKeepsTheTicketAndCountsDown() {
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("code", "admission_paused")
                    put("params", buildJsonObject { put("retry_after_s", 30) })
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val (session, store) = session(binding = Samples.binding.copy(token = "", ticket = "ticket-1"))
        eventually("paused") { session.view.value.waitReason == HubWaitReason.ADMISSION_PAUSED }
        assertEquals(CLOCK_MILLIS + 30_000, session.view.value.nextRoundAtMillis)
        assertEquals("ticket-1", store.get("b1")?.ticket)
    }

    @Test
    fun aJoinRefusedControlUnavailableJoinsAgainAfterItsSeconds() {
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("code", "control_unavailable")
                    put("params", buildJsonObject { put("retry_after_s", 5) })
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val (session, store) = session(binding = Samples.binding.copy(token = "", ticket = "ticket-1"))
        assertTrue(fake.nextCommand("join") != null)
        eventually("waiting") { session.view.value.waitReason == HubWaitReason.HUB_SILENT }
        assertEquals(CLOCK_MILLIS + 5_000, session.view.value.nextRoundAtMillis)
        assertEquals("ticket-1", store.get("b1")?.ticket)
        assertNull(fake.nextCommand("join", seconds = 3))
        assertTrue(fake.nextCommand("join", seconds = 4) != null)
    }

    @Test
    fun aJoinRefusedControlUnavailableWithNoSecondsWaitsAMinute() {
        fake.answer = { line ->
            if (FakeTransport.text(line, "command") == "join") {
                buildJsonObject {
                    put("code", "control_unavailable")
                    put("params", JsonObject(emptyMap()))
                }
            } else {
                JsonObject(emptyMap())
            }
        }
        val (session, _) = session(binding = Samples.binding.copy(token = "", ticket = "ticket-1"))
        eventually("waiting") { session.view.value.waitReason == HubWaitReason.HUB_SILENT }
        assertEquals(CLOCK_MILLIS + 60_000, session.view.value.nextRoundAtMillis)
    }

    @Test
    fun anOldBindingDialsNothing() {
        val (session, _) = session(binding = Samples.binding.copy(hubKey = "", privateKey = ""))
        eventually("refused") { session.view.value.waitReason == HubWaitReason.JOIN_REFUSED }
        assertEquals("hub_key_missing", session.view.value.waitRefusal?.code)
        assertNull(fake.nextCommand("dial", seconds = 1))
    }

    private object Json {
        fun state(): JsonObject = kotlinx.serialization.json.Json.parseToJsonElement(
            """
            {"type":"state","hash":"h9","urls":["$LAN"],"reached_through":"lan",
             "services":[{"id":"gitea_d1_web","type":"web","title":"Gitea","payload":{"url":"http://10.0.0.5:3000/"},
                          "source":"module","device_id":"d1","device_name":"lab","app_id":"gitea_d1","name":"web",
                          "local_port":27311}],
             "apps":[{"id":"gitea_d1","title":"Gitea","source":"module","device_id":"d1","device_name":"lab",
                      "local_name":"gitea.lab.localhost"}],
             "terminals":[{"device_id":"d1","name":"lab","is_online":true,"accounts":["iffi","lab"],"sessions":[]}]}
            """.trimIndent(),
        ).jsonObject
    }

    private companion object {
        const val CLOCK_MILLIS = 1_000_000L
        const val LAN = "tcp://192.168.100.1:8443"
    }
}
