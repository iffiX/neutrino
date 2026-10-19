import Darwin
import XCTest

@testable import Neutrino

final class ClientCoreTests: XCTestCase {
    private var transport = FakeHubTransport()
    private var clock = FakeClientClock()
    private var defaults = UserDefaults()
    private var suite = ""

    override func setUp() {
        transport = FakeHubTransport()
        clock = FakeClientClock()
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    private func core() -> ClientCore {
        ClientCore(
            secrets: FakeSecretStore(), transport: transport, clock: clock, defaults: defaults, device: Samples.device,
            edition: Client.editionIntl, hasNetwork: { true }, resolveHubName: { $0(nil) }, localNetworks: { [] },
            bundle: Bundle(for: ClientCore.self))
    }

    private func joinAndConnect(_ core: ClientCore) throws -> FakeChannelSocket {
        core.join(
            Samples.link([
                "urls": .array([.string("https://192.168.1.1:8443")]), "token": .string("TICKET"),
                "fp": .string(Samples.fingerprint), "role": .string("client"),
            ]))
        XCTAssertNotNil(core.joining.joinedId)
        let socket = try XCTUnwrap(transport.sockets.first)
        socket.deliver(.opened)
        transport.posts.first?.completion(.success(["id": .string("hub-binding"), "token": .string("tok")]))
        socket.deliver(frame: Samples.welcome)
        socket.deliver(
            frame: Samples.state([
                "services": .array([
                    .object([
                        "id": .string("gitea"), "type": .string("web"), "title": .string("Gitea"),
                        "payload": .object(["url": .string("http://10.0.0.5:3000/explore")]),
                        "source": .string("module"),
                    ])
                ])
            ]))
        return socket
    }

    private func isListening(_ port: Int) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return connected == 0
    }

    private func turnMainQueue() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }

    func testAJoinKeepsTheBindingAndTheHubsRowConnectsOnItsFirstRound() throws {
        let core = self.core()
        _ = try joinAndConnect(core)
        XCTAssertEqual(core.hubs.count, 1)
        XCTAssertEqual(core.hubs.first?.connection, .connected)
        XCTAssertEqual(core.hubs.first?.binding.hubName, "Home")
    }

    func testOpenOnAWebEntryForwardsItAndOpensTheInAppBrowserOnTheLoopback() throws {
        let core = self.core()
        _ = try joinAndConnect(core)
        let hub = try XCTUnwrap(core.hubs.first)
        let entry = try XCTUnwrap(hub.services(of: "web").first)
        core.openWeb(bindingId: hub.binding.id, entry: entry)
        let row = try XCTUnwrap(core.forwardRows[WebForwards.key(hub.binding.id, "gitea")])
        XCTAssertTrue(row.isForwarded)
        XCTAssertNil(row.job)
        XCTAssertEqual(core.browser?.url, "http://127.0.0.1:\(row.localPort)/explore")
        XCTAssertTrue(isListening(row.localPort))
        core.disconnectWeb(bindingId: hub.binding.id, entryId: "gitea")
        turnMainQueue()
    }

    func testTheEndOfTheBackgroundTimeClosesEveryChannelAndListenerAndTheReturnListensAgainOnTheSamePort() throws {
        let core = self.core()
        let socket = try joinAndConnect(core)
        let hub = try XCTUnwrap(core.hubs.first)
        core.openWeb(bindingId: hub.binding.id, entry: try XCTUnwrap(hub.services(of: "web").first))
        let port = try XCTUnwrap(core.forwardRows[WebForwards.key(hub.binding.id, "gitea")]?.localPort)
        XCTAssertTrue(isListening(port))

        core.suspend()
        turnMainQueue()
        XCTAssertTrue(socket.isClosed)
        XCTAssertFalse(isListening(port))
        XCTAssertEqual(transport.sockets.count, 1)

        core.foreground()
        turnMainQueue()
        XCTAssertEqual(transport.sockets.count, 2)
        XCTAssertTrue(isListening(port))
        XCTAssertEqual(core.forwardRows[WebForwards.key(hub.binding.id, "gitea")]?.localPort, port)
        core.disconnectWeb(bindingId: hub.binding.id, entryId: "gitea")
        turnMainQueue()
    }

    func testLeavingAHubForgetsItsBindingAtOnceAndTellsTheHub() throws {
        let core = self.core()
        _ = try joinAndConnect(core)
        let id = try XCTUnwrap(core.hubs.first?.binding.id)
        core.leave(id)
        XCTAssertTrue(core.hubs.isEmpty)
        XCTAssertEqual(transport.posts.last?.path, Channel.leavePath)
    }
}
