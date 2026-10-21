import XCTest

@testable import Neutrino

final class WebForwardsTests: XCTestCase {
    private let socket = FakeChannelSocket(url: "https://192.168.1.1:8443")
    private let clock = FakeClientClock()
    private var registry: ChannelStreamRegistry?
    private var defaults = UserDefaults()
    private var suite = ""
    private var forwards: WebForwards?
    private var opened: [String] = []

    override func setUp() {
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        self.registry = registry
        forwards = WebForwards(
            table: LocalPortTable(defaults: defaults),
            openConnect: { _, args in registry.open(kind: Channel.kindConnect, args: args, hasBytes: true) },
            material: { _, _, completion in completion(.success(["token": .string("one-time")])) })
        opened = []
    }

    override func tearDown() {
        forwards?.forget(bindingId: "b1")
        turnMainQueue()
        defaults.removePersistentDomain(forName: suite)
    }

    private func hub(isUp: Bool) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = isUp ? .connected : .connecting
        hub.connectedAddress = isUp ? "https://192.168.1.1:8443" : ""
        hub.isPanelAllowed = true
        hub.services = [
            ChannelServiceEntry.of(
                .object([
                    "id": .string("code"), "type": .string("web"), "title": .string("code-server"),
                    "payload": .object([
                        "url": .string("http://10.0.0.5:8080/editor"), "is_token_required": .bool(true),
                    ]),
                ]))!
        ]
        return hub
    }

    private func turnMainQueue() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }

    private func openEditor() throws -> Int {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.take([hub(isUp: true)])
        forwards.open(bindingId: "b1", entryId: "code", url: "http://10.0.0.5:8080/editor", isTokenRequired: true) {
            self.opened.append($0)
        }
        return try XCTUnwrap(forwards.rows["b1/code"]?.localPort)
    }

    func testOpenReadsAFreshTokenAndOpensTheLoopbackAddressWithIt() throws {
        let port = try openEditor()
        XCTAssertEqual(opened, ["http://127.0.0.1:\(port)/editor?tkn=one-time"])
        XCTAssertNil(forwards?.rows["b1/code"]?.job)
    }

    func testEveryAcceptedConnectionIsOneConnectStreamCarryingItsBytesBothWays() throws {
        let port = try openEditor()
        let client = try XCTUnwrap(LoopbackClient(port: port))
        turnMainQueue()
        let open = try XCTUnwrap(socket.frames.first { $0.text("type") == "open" })
        XCTAssertEqual(open.text("kind"), "connect")
        XCTAssertEqual(open.text("id"), "code")
        let stream = try XCTUnwrap(open.number("stream").map(UInt32.init))

        client.write(Data("GET /".utf8))
        turnMainQueue()
        XCTAssertTrue(socket.binaries.isEmpty)
        registry?.takeCredit(stream: stream, bytes: 1000)
        XCTAssertEqual(socket.binaries.last, ChannelFrames.binary(stream: stream, bytes: Data("GET /".utf8)))

        registry?.takeBinary(ChannelFrames.binary(stream: stream, bytes: Data("200 OK".utf8)))
        turnMainQueue()
        XCTAssertEqual(client.read(), Data("200 OK".utf8))
    }

    func testAForwardWaitsForItsHubsChannel() throws {
        let port = try openEditor()
        forwards?.take([hub(isUp: false)])
        let client = try XCTUnwrap(LoopbackClient(port: port))
        turnMainQueue()
        XCTAssertFalse(socket.frameTypes.contains("open"))
        forwards?.take([hub(isUp: true)])
        turnMainQueue()
        XCTAssertEqual(socket.frameTypes.filter { $0 == "open" }.count, 1)
        _ = client
    }

    func testAForwardStopsWhenItsHubWithdrawsTheEntry() throws {
        _ = try openEditor()
        var withdrawn = hub(isUp: true)
        withdrawn.services = []
        forwards?.take([withdrawn])
        XCTAssertNil(forwards?.rows["b1/code"])
    }

    func testConfigureIsRefusedWhileTheEntryIsForwarded() throws {
        _ = try openEditor()
        XCTAssertThrowsError(
            try forwards?.configure(
                bindingId: "b1", entryId: "code", choice: LocalPortChoice(isFixed: true, port: 30000))
        ) { error in
            XCTAssertEqual((error as? ClientError)?.code, "disconnect_first")
        }
    }

    func testAHeldForwardShowsOnNoRowCarriesItsEntrysStreamsAndEndsWithItsRelease() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.take([hub(isUp: true)])
        let port = try forwards.hold(bindingId: "b1", entryId: "code", port: 0).get()
        XCTAssertNil(forwards.rows["b1/code"])
        let client = try XCTUnwrap(LoopbackClient(port: port))
        turnMainQueue()
        let open = try XCTUnwrap(socket.frames.first { $0.text("type") == "open" })
        XCTAssertEqual(open.text("kind"), "connect")
        XCTAssertEqual(open.text("id"), "code")
        XCTAssertEqual(try forwards.hold(bindingId: "b1", entryId: "code", port: 0).get(), port)

        forwards.release(bindingId: "b1", entryId: "code")
        turnMainQueue()
        XCTAssertNil(LoopbackClient(port: port))
        _ = client
    }

    func testAHeldForwardEndsWhenItsHubWithdrawsTheEntry() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.take([hub(isUp: true)])
        let port = try forwards.hold(bindingId: "b1", entryId: "code", port: 0).get()
        var withdrawn = hub(isUp: true)
        withdrawn.services = []
        forwards.take([withdrawn])
        turnMainQueue()
        XCTAssertNil(LoopbackClient(port: port))
    }

    func testThePanelOpensWithItsSignInToken() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.take([hub(isUp: true)])
        forwards.openPanel(bindingId: "b1") { self.opened.append($0) }
        let port = try XCTUnwrap(forwards.rows[WebForwards.panelKey("b1")]?.localPort)
        XCTAssertEqual(opened, ["http://127.0.0.1:\(port)/?tkn=one-time"])
    }
}
