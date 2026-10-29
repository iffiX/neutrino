import XCTest

@testable import Neutrino

final class HubSessionTests: XCTestCase {
    private var fake = FakeTransport()
    private var clock = FakeClientClock()
    private var transport: ClientTransport?
    private var store = BindingStore(secrets: FakeSecretStore())
    private var joined: [(String, String)] = []
    private var hasNetwork = true

    private let lan = "tcp://192.168.1.1:8443"
    private let wan = "tcp://203.0.113.7:8443"

    override func setUp() {
        fake = FakeTransport()
        clock = FakeClientClock()
        store = BindingStore(secrets: FakeSecretStore())
        joined = []
        hasNetwork = true
        let transport = ClientTransport(library: fake, directory: "/data", dialerOf: { _ in self.fake }, clock: clock)
        transport.start()
        self.transport = transport
    }

    private func session(_ binding: HubBinding = Samples.binding) throws -> HubSession {
        try store.put(binding)
        let session = HubSession(
            bindingId: binding.id, store: store, transport: try XCTUnwrap(transport), machine: Samples.machine,
            clock: clock, resolveHubName: { $0(nil) },
            localNetworks: { [ChannelLocalNetwork(address: [192, 168, 1, 7], prefix: 24)] },
            hasNetwork: { self.hasNetwork }, onJoined: { self.joined.append(($0, $1)) })
        session.start()
        return session
    }

    private func connected(_ session: HubSession) {
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        fake.event("session_open", "b1", ["address": .string(lan), "path": .string("lan"), "handshake_ms": .int(4)])
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("hello").isEmpty })
        fake.frame("b1", Samples.welcome)
        XCTAssertTrue(RunLoopWait.until { session.view.isConnected })
    }

    func testABoundBindingDialsEveryCandidateWithItsPathKeyAndPsk() throws {
        var binding = Samples.binding
        binding.overlays = [ChannelOverlay(provider: "netbird", hubAddress: "100.88.0.1")]
        let session = try self.session(binding)
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        XCTAssertEqual(session.view.connection, .connecting)
        let dial = try XCTUnwrap(fake.sent("dial").first)
        XCTAssertEqual(dial.text("binding"), "b1")
        XCTAssertEqual(dial.text("hub_key"), Samples.hubKey)
        XCTAssertEqual(dial.text("private_key"), Samples.privateKey)
        XCTAssertEqual(dial.text("psk"), binding.psk)
        XCTAssertEqual(dial.text("role"), "client")
        let candidates = (dial["candidates"]?.arrayValue ?? []).compactMap(\.objectValue).map {
            "\($0.text("address")) \($0.text("path"))"
        }
        XCTAssertEqual(candidates, ["tcp://100.88.0.1:8443 netbird", "\(lan) lan", "\(wan) direct"])
    }

    func testASessionIsGreetedWithAHelloOfNoTokenAndTheWelcomeConnectsReportsAndPings() throws {
        var welcomed: [String] = []
        try store.put(Samples.binding)
        let session = HubSession(
            bindingId: "b1", store: store, transport: try XCTUnwrap(transport), machine: Samples.machine,
            clock: clock, resolveHubName: { $0(nil) }, localNetworks: { [] }, hasNetwork: { true },
            onJoined: { _, _ in }, onWelcomed: { _, hubId in welcomed.append(hubId) })
        session.start()
        connected(session)
        let hello = try XCTUnwrap(fake.written("hello").first)
        XCTAssertNil(hello["token"])
        XCTAssertEqual(GoldenSchema.problems(.object(hello.filter { $0.key != "type" }), "ChannelHello"), [])
        XCTAssertEqual(welcomed, ["hub-1"])
        XCTAssertEqual(session.view.software, "neutrino_hub/0.6.0")
        XCTAssertEqual(session.view.connectedAddress, lan)
        XCTAssertEqual(store.get("b1")?.gatewayUrl, lan)
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("report").isEmpty && !self.fake.written("ping").isEmpty })
    }

    func testThePongOfTheLastPingSetsTheRoundTrip() throws {
        let session = try self.session()
        connected(session)
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("ping").isEmpty })
        let nonce = try XCTUnwrap(fake.written("ping").last?.text("nonce"))
        clock.advance(by: 0.007)
        fake.frame("b1", ["type": .string("pong"), "nonce": .string("another")])
        fake.frame("b1", ["type": .string("pong"), "nonce": .string(nonce)])
        XCTAssertTrue(RunLoopWait.until { session.view.rttMs == 7 })
    }

    func testAStateFrameIsTakenAndReportedBackWithItsHash() throws {
        let session = try self.session()
        connected(session)
        fake.frame(
            "b1",
            Samples.state(
                hash: "h9",
                [
                    "urls": .array([.string(lan)]),
                    "services": .array([
                        .object([
                            "id": .string("gitea_d1_web"), "type": .string("web"), "title": .string("Gitea"),
                            "payload": .object(["url": .string("http://10.0.0.5:3000/")]), "source": .string("module"),
                            "app_id": .string("gitea_d1"), "name": .string("web"), "local_port": .int(27311),
                        ])
                    ]),
                    "apps": .array([
                        .object([
                            "id": .string("gitea_d1"), "title": .string("Gitea"), "source": .string("module"),
                            "local_name": .string("gitea.lab.localhost"),
                        ])
                    ]),
                    "terminals": .array([
                        .object([
                            "device_id": .string("d1"), "name": .string("lab"), "accounts": .array([.string("iffi")]),
                        ])
                    ]),
                ]))
        XCTAssertTrue(RunLoopWait.until { !session.view.apps.isEmpty })
        XCTAssertEqual(session.view.services.first?.localPort, 27311)
        XCTAssertEqual(session.view.services.first?.appId, "gitea_d1")
        XCTAssertEqual(session.view.terminals.first?.accounts, ["iffi"])
        XCTAssertEqual(store.get("b1")?.gatewayUrls, [lan])
        XCTAssertTrue(RunLoopWait.until { self.fake.written("report").contains { $0.text("state_hash") == "h9" } })
    }

    func testAServiceFrameIsAnsweredByTheReplyOfItsRequest() throws {
        let session = try self.session()
        connected(session)
        var answer: Result<[String: JSONValue], ClientError>?
        session.openService(args: ["id": .string("rdp_d1")]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("service").isEmpty })
        let service = try XCTUnwrap(fake.written("service").first)
        XCTAssertEqual(GoldenSchema.problems(.object(service.filter { $0.key != "type" }), "ChannelService"), [])
        fake.frame(
            "b1",
            [
                "type": .string("reply"), "request": .string(service.text("request")), "code": .string(""),
                "params": .object(["password": .string("seat")]),
            ])
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        guard case .success(let material) = answer else { return XCTFail("the reply was refused") }
        XCTAssertEqual(material.text("password"), "seat")
    }

    func testAReplyThatNeverComesIsUnreachableAtItsTimeout() throws {
        let session = try self.session()
        connected(session)
        var answer: Result<[String: JSONValue], ClientError>?
        session.stopSession("s1") { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("stop_session").isEmpty })
        clock.advance(by: Channel.streamTimeoutSeconds)
        guard case .failure(let refusal) = answer else { return XCTFail("the stop was answered") }
        XCTAssertEqual(refusal.code, Channel.codeHubUnreachable)
    }

    func testARoundThatEndsWithNoSessionWaitsTheSecondsTheTransportNames() throws {
        let session = try self.session()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        fake.event("round_end", "b1", ["code": .string("hub_unreachable"), "next_round_s": .int(10)])
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .hubSilent })
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 10)
        clock.advance(by: 10)
        XCTAssertEqual(session.view.connection, .connecting)
    }

    func testARunOfControlUnavailableRefusalsWritesFourLines() throws {
        var lines: [String] = []
        try store.put(Samples.binding)
        let session = HubSession(
            bindingId: "b1", store: store, transport: try XCTUnwrap(transport), machine: Samples.machine,
            clock: clock, resolveHubName: { $0(nil) }, localNetworks: { [] }, hasNetwork: { true },
            onJoined: { _, _ in }, writeLog: { lines.append($0) })
        session.start()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        for turn in 0..<30 {
            if turn > 0 { clock.advance(by: 5) }
            let due = clock.now + 5
            fake.event("round_end", "b1", ["code": .string("control_unavailable"), "next_round_s": .int(5)])
            XCTAssertTrue(RunLoopWait.until { session.view.nextRoundAt == due })
        }
        connected(session)
        let title = Samples.binding.title
        XCTAssertEqual(
            lines.filter { $0.contains("control_unavailable") },
            [
                "hub \(title): waiting on hub_silent for 5s: control_unavailable",
                "hub \(title): waiting on hub_silent for 5s: control_unavailable, 12 times since the last line",
                "hub \(title): waiting on hub_silent for 5s: control_unavailable, 12 times since the last line",
                "hub \(title): the hub welcomed this client; refused control_unavailable 5 times since the last line",
            ])
    }

    func testAKeyThatOpensUnderNoPskIsAMismatch() throws {
        let session = try self.session()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        fake.event("round_end", "b1", ["code": .string("hub_untrusted"), "next_round_s": .int(60)])
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .untrusted })
    }

    func testARoundWithNoNetworkWaitsForTheNetwork() throws {
        hasNetwork = false
        let session = try self.session()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        fake.event("round_end", "b1", ["code": .string("hub_unreachable"), "next_round_s": .int(5)])
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .noNetwork })
        XCTAssertEqual(session.view.nextRoundAt, 0)
    }

    func testASessionAnotherClientTookWaitsForReconnectWhichDialsAgain() throws {
        let session = try self.session()
        connected(session)
        fake.event("session_end", "b1", ["code": .string("replaced")])
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .replaced })
        XCTAssertFalse(session.refresh())
        session.reconnect()
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("dial").count == 2 })
    }

    func testAHubThatDoesNotKnowTheBindingLeavesLeaveAsTheOnlyAction() throws {
        let session = try self.session()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        fake.event("round_end", "b1", ["code": .string("binding_unknown"), "next_round_s": .int(0)])
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .unknownDevice })
        XCTAssertTrue(session.view.isLeaveOnly)
    }

    func testASessionThatDropsReadsConnecting() throws {
        let session = try self.session()
        connected(session)
        fake.event("session_end", "b1")
        XCTAssertTrue(RunLoopWait.until { session.view.connection == .connecting })
        XCTAssertNil(session.view.rttMs)
        XCTAssertEqual(session.view.connectedAddress, "")
    }

    func testAMoveGreetsTheNewSessionAndStaysConnected() throws {
        let session = try self.session()
        connected(session)
        fake.event("session_open", "b1", ["address": .string(wan), "path": .string("direct"), "handshake_ms": .int(2)])
        XCTAssertTrue(RunLoopWait.until { self.fake.written("hello").count == 2 })
        XCTAssertTrue(session.view.isConnected)
        fake.frame("b1", Samples.welcome)
        XCTAssertTrue(RunLoopWait.until { session.view.connectedAddress == self.wan })
    }

    func testARefreshReportsWithIsRefreshWhileConnectedAndStartsARoundOtherwise() throws {
        let session = try self.session()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        XCTAssertTrue(session.refresh())
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("round").isEmpty })
        fake.event("session_open", "b1", ["address": .string(lan), "path": .string("lan"), "handshake_ms": .int(4)])
        XCTAssertTrue(RunLoopWait.until { !self.fake.written("hello").isEmpty })
        fake.frame("b1", Samples.welcome)
        fake.frame("b1", Samples.state())
        XCTAssertTrue(RunLoopWait.until { !session.view.jobs.isRefreshing })
        XCTAssertTrue(session.refresh())
        XCTAssertTrue(RunLoopWait.until { self.fake.written("report").contains { $0.flag("is_refresh") } })
    }

    func testAPendingBindingSpendsItsTicketWithTheTransportsJoinThenDials() throws {
        var pending = Samples.binding
        pending.token = ""
        pending.ticket = "ticket-1"
        fake.answer = { line in
            line.text("command") == "join" ? ["binding_id": .string("c9"), "token": .string("t9")] : [:]
        }
        let session = try self.session(pending)
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("dial").isEmpty })
        XCTAssertEqual(session.view.binding.boundId, "c9")
        let join = try XCTUnwrap(fake.sent("join").first)
        let body = join.filter { GoldenSchema.properties("ChannelJoin").contains($0.key) }
        XCTAssertEqual(GoldenSchema.problems(.object(body), "ChannelJoin"), [])
        XCTAssertEqual(join.text("ticket"), "ticket-1")
        XCTAssertEqual(join["addresses"], .array([.string(lan), .string(wan)]))
        XCTAssertEqual(store.get("b1")?.token, "t9")
        XCTAssertEqual(store.get("b1")?.boundId, "c9")
        XCTAssertEqual(store.get("b1")?.ticket, "")
        XCTAssertEqual(joined.map { "\($0.0) \($0.1)" }, ["b1 c9"])
    }

    func testARefusedTicketHoldsTheRowOnJoinRefusedWithNoRound() throws {
        var pending = Samples.binding
        pending.token = ""
        pending.ticket = "ticket-1"
        fake.answer = { line in
            line.text("command") == "join" ? ["code": .string("ticket_spent"), "params": .object([:])] : [:]
        }
        let session = try self.session(pending)
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .joinRefused })
        XCTAssertEqual(session.view.waitRefusal?.code, "ticket_spent")
        RunLoopWait.turn()
        XCTAssertTrue(fake.sent("dial").isEmpty)
    }

    func testAPausedAdmissionKeepsTheTicketAndJoinsAgainAfterItsSeconds() throws {
        var pending = Samples.binding
        pending.token = ""
        pending.ticket = "ticket-1"
        fake.answer = { line in
            line.text("command") == "join"
                ? ["code": .string("admission_paused"), "params": .object(["retry_after_s": .int(30)])] : [:]
        }
        let session = try self.session(pending)
        XCTAssertTrue(RunLoopWait.until { session.view.waitReason == .admissionPaused })
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 30)
        XCTAssertEqual(store.get("b1")?.ticket, "ticket-1")
        clock.advance(by: 30)
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("join").count == 2 })
    }

    func testABindingOf05DialsNothingAndWaitsForLeave() throws {
        var old = Samples.binding
        old.hubKey = ""
        let session = try self.session(old)
        XCTAssertEqual(session.view.waitReason, .joinRefused)
        XCTAssertEqual(session.view.waitRefusal?.code, Channel.codeHubKeyMissing)
        RunLoopWait.turn()
        XCTAssertTrue(fake.sent("dial").isEmpty)
    }

    func testASuspendUndialsAndTheForegroundDialsAgainAtOnce() throws {
        let session = try self.session()
        connected(session)
        session.suspend()
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("undial").isEmpty })
        XCTAssertFalse(session.view.isConnected)
        session.foreground()
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("dial").count == 2 })
    }
}
