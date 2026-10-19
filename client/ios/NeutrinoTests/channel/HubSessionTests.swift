import XCTest

@testable import Neutrino

final class HubSessionTests: XCTestCase {
    private var transport = FakeHubTransport()
    private var clock = FakeClientClock()
    private var store = BindingStore(secrets: FakeSecretStore())
    private var localNetworks: [ChannelLocalNetwork] = []
    private var joined: [(String, String)] = []

    private let lan = "https://192.168.1.1:8443"
    private let wan = "https://203.0.113.7:8443"
    private let refused = ClientError.refusal(Channel.codeHubUnreachable, ["detail": "Connection refused"])

    override func setUp() {
        transport = FakeHubTransport()
        clock = FakeClientClock()
        store = BindingStore(secrets: FakeSecretStore())
        localNetworks = []
        joined = []
    }

    private func session(_ binding: HubBinding = Samples.binding) throws -> HubSession {
        try store.put(binding)
        let session = HubSession(
            bindingId: binding.id, store: store, transport: transport, machine: Samples.machine, clock: clock,
            resolveHubName: { $0(nil) }, localNetworks: { self.localNetworks }, hasNetwork: { true },
            onJoined: { self.joined.append(($0, $1)) })
        session.start()
        return session
    }

    private func connect(_ session: HubSession, on url: String) -> FakeChannelSocket? {
        guard let socket = transport.sockets(to: url).last else { return nil }
        socket.deliver(.opened)
        socket.deliver(frame: Samples.welcome)
        return socket
    }

    func testARoundDialsEveryVirtualNetworkAddress() throws {
        var binding = Samples.binding
        binding.overlays = [
            ChannelOverlay(provider: "netbird", hubAddress: "100.88.0.1"),
            ChannelOverlay(provider: "easytier", hubAddress: "10.0.0.1"),
        ]
        _ = try session(binding)
        XCTAssertEqual(
            Set(transport.sockets.map(\.url)), ["https://100.88.0.1:8443", "https://10.0.0.1:8443", lan, wan])
    }

    func testTheWinnerAloneSaysHelloAndAWelcomeConnectsReportsAndPings() throws {
        let session = try self.session()
        XCTAssertEqual(session.view.connection, .connecting)
        transport.sockets(to: wan)[0].deliver(.opened)
        let socket = transport.sockets(to: wan)[0]
        XCTAssertEqual(socket.frameTypes, ["hello"])
        XCTAssertTrue(transport.sockets(to: lan)[0].isClosed)
        XCTAssertTrue(transport.sockets(to: lan)[0].texts.isEmpty)
        socket.deliver(frame: Samples.welcome)
        XCTAssertEqual(session.view.connection, .connected)
        XCTAssertEqual(session.view.connectedAddress, wan)
        XCTAssertEqual(session.view.software, "neutrino_hub/0.6.0")
        XCTAssertEqual(socket.frameTypes, ["hello", "report", "ping"])
        XCTAssertEqual(store.get("b1")?.gatewayUrl, wan)
    }

    func testEveryAddressFailingWaitsAsHubSilentFiveSecondsThenTen() throws {
        let session = try self.session()
        for socket in transport.sockets { socket.deliver(.failed(refused, isPortClosed: false)) }
        XCTAssertEqual(session.view.connection, .waiting)
        XCTAssertEqual(session.view.waitReason, .hubSilent)
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 5)
        clock.advance(by: 5)
        XCTAssertEqual(session.view.connection, .connecting)
        XCTAssertEqual(transport.sockets.count, 4)
        for socket in transport.sockets.suffix(2) { socket.deliver(.failed(refused, isPortClosed: false)) }
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 10)
    }

    func testAnotherCertificateOnAStoredAddressWaitsAMinuteAsUntrusted() throws {
        let session = try self.session()
        let untrusted = ClientError.refusal(Channel.codeHubUntrusted, ["url": lan])
        transport.sockets(to: lan)[0].deliver(.failed(untrusted, isPortClosed: false))
        transport.sockets(to: wan)[0].deliver(.failed(refused, isPortClosed: false))
        XCTAssertEqual(session.view.waitReason, .untrusted)
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 60)
    }

    func testAPendingBindingSpendsItsTicketAtTheWinnersAddressThenSaysHelloWithTheToken() throws {
        var binding = Samples.binding
        binding.token = ""
        binding.ticket = "TICKET"
        binding.hubBindingId = ""
        let session = try self.session(binding)
        transport.sockets(to: lan)[0].deliver(.opened)
        XCTAssertEqual(transport.posts.map(\.baseUrl), [lan])
        XCTAssertEqual(transport.posts[0].path, Channel.joinPath)
        XCTAssertEqual(transport.posts[0].body.text("ticket"), "TICKET")
        XCTAssertTrue(transport.sockets(to: lan)[0].texts.isEmpty)
        transport.posts[0].completion(.success(["id": .string("hub-binding"), "token": .string("tok")]))
        let hello = transport.sockets(to: lan)[0].frames.first
        XCTAssertEqual(hello?.text("token"), "tok")
        XCTAssertEqual(hello?.text("id"), "hub-binding")
        XCTAssertEqual(store.get("b1")?.ticket, "")
        XCTAssertEqual(joined.first?.1, "hub-binding")
        transport.sockets(to: lan)[0].deliver(frame: Samples.welcome)
        XCTAssertEqual(session.view.connection, .connected)
    }

    func testARefusedTicketHoldsTheRowOnJoinRefusedWithNoMoreRounds() throws {
        var binding = Samples.binding
        binding.ticket = "TICKET"
        let session = try self.session(binding)
        transport.sockets(to: lan)[0].deliver(.opened)
        transport.posts[0].completion(.failure(.refusal("ticket_spent")))
        XCTAssertEqual(session.view.waitReason, .joinRefused)
        XCTAssertEqual(session.view.waitRefusal?.code, "ticket_spent")
        XCTAssertTrue(session.view.isLeaveOnly)
        clock.advance(by: 120)
        XCTAssertEqual(transport.sockets.count, 2)
    }

    func testAPausedAdmissionWaitsTheSecondsItNamesAndJoinsAgain() throws {
        var binding = Samples.binding
        binding.ticket = "TICKET"
        let session = try self.session(binding)
        transport.sockets(to: lan)[0].deliver(.opened)
        transport.posts[0].completion(.failure(.refused(code: "admission_paused", params: ["retry_after_s": .int(7)])))
        XCTAssertEqual(session.view.waitReason, .admissionPaused)
        XCTAssertEqual(session.view.nextRoundAt, clock.now + 7)
        clock.advance(by: 7)
        XCTAssertEqual(session.view.connection, .connecting)
    }

    func testThePongOfTheLastPingSetsTheRoundTrip() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        let nonce = socket.frames.last { $0.text("type") == "ping" }?.text("nonce") ?? ""
        XCTAssertFalse(nonce.isEmpty)
        clock.advance(by: 0.012)
        socket.deliver(frame: ["type": .string("pong"), "nonce": .string("other")])
        XCTAssertNil(session.view.rttMs)
        socket.deliver(frame: ["type": .string("pong"), "nonce": .string(nonce)])
        XCTAssertEqual(session.view.rttMs, 12)
        clock.advance(by: 20)
        XCTAssertEqual(socket.frameTypes.filter { $0 == "ping" }.count, 2)
    }

    func testAStateFrameIsTakenAndReportedBackWithItsHash() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        socket.deliver(
            frame: Samples.state(
                hash: "h9",
                [
                    "reached_through": .string("ssh_relay"), "is_panel_allowed": .bool(true),
                    "services": .array([
                        .object([
                            "id": .string("gitea"), "type": .string("web"), "title": .string("Gitea"),
                            "payload": .object(["url": .string("http://10.0.0.5:3000")]), "source": .string("module"),
                        ])
                    ]),
                ]))
        XCTAssertEqual(session.view.reachedThrough, "ssh_relay")
        XCTAssertTrue(session.view.isPanelAllowed)
        XCTAssertEqual(session.view.services(of: "web").map(\.id), ["gitea"])
        XCTAssertEqual(socket.frames.last?.text("type"), "report")
        XCTAssertEqual(socket.frames.last?.text("state_hash"), "h9")
    }

    func testARefreshOnAConnectedHubAsksForTheWholeState() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        XCTAssertTrue(session.refresh())
        XCTAssertTrue(session.view.jobs.isRefreshing)
        XCTAssertEqual(socket.frames.last?.text("type"), "report")
        XCTAssertTrue(socket.frames.last?.flag("is_refresh") ?? false)
        socket.deliver(frame: Samples.state())
        XCTAssertFalse(session.view.jobs.isRefreshing)
    }

    func testASocketReplacedByAnotherClientWaitsForReconnect() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        socket.deliver(.closed(code: Channel.closeReplaced))
        XCTAssertEqual(session.view.waitReason, .replaced)
        clock.advance(by: 120)
        XCTAssertEqual(transport.sockets.count, 2)
        session.reconnect()
        XCTAssertEqual(transport.sockets.count, 4)
    }

    func testAHubThatDoesNotKnowTheBindingLeavesLeaveAsTheOnlyAction() throws {
        let session = try self.session()
        transport.sockets(to: lan)[0].deliver(.opened)
        transport.sockets(to: lan)[0].deliver(frame: ["type": .string("refused"), "code": .string("binding_unknown")])
        XCTAssertEqual(session.view.waitReason, .unknownDevice)
        XCTAssertTrue(session.view.isLeaveOnly)
    }

    func testAClientTooOldWaitsWithTheUpdateItNeeds() throws {
        let session = try self.session()
        transport.sockets(to: lan)[0].deliver(.opened)
        transport.sockets(to: lan)[0].deliver(
            frame: ["type": .string("refused"), "code": .string("protocol_too_old"), "params": .object([:])])
        XCTAssertEqual(session.view.waitReason, .tooOld)
    }

    func testADroppedSocketRunsTheNextRoundAtOnce() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        socket.deliver(.closed(code: 1006))
        XCTAssertEqual(session.view.connection, .connecting)
        XCTAssertEqual(transport.sockets.count, 4)
    }

    func testANetworkChangeMovesTheChannelToABetterPathAndKeepsItOnAWorseOne() throws {
        localNetworks = [ChannelLocalNetwork(address: [192, 168, 1, 20], prefix: 24)]
        let session = try self.session()
        let direct = try XCTUnwrap(connect(session, on: wan))
        session.networkChanged()
        let better = try XCTUnwrap(transport.sockets(to: lan).last)
        better.deliver(.opened)
        XCTAssertEqual(better.frameTypes, ["hello"])
        direct.deliver(.closed(code: Channel.closeReplaced))
        better.deliver(frame: Samples.welcome)
        XCTAssertEqual(session.view.connectedAddress, lan)
        XCTAssertNil(session.view.waitReason)
        XCTAssertTrue(direct.isClosed)
        session.networkChanged()
        transport.sockets(to: wan).last?.deliver(.opened)
        XCTAssertTrue(transport.sockets(to: wan).last?.isClosed ?? false)
        XCTAssertEqual(transport.sockets(to: wan).last?.texts, [])
        XCTAssertEqual(session.view.connectedAddress, lan)
    }

    func testASuspendClosesTheSocketAndTheForegroundRunsARoundAtOnce() throws {
        let session = try self.session()
        let socket = try XCTUnwrap(connect(session, on: lan))
        session.suspend()
        XCTAssertTrue(socket.isClosed)
        clock.advance(by: 120)
        XCTAssertEqual(transport.sockets.count, 2)
        session.foreground()
        XCTAssertEqual(transport.sockets.count, 4)
    }
}
