import XCTest

@testable import Neutrino

final class HubConnectionsTests: XCTestCase {
    private var transport = FakeHubTransport()
    private var clock = FakeClientClock()
    private var store = BindingStore(secrets: FakeSecretStore())
    private var left: [String] = []

    private let oldUrl = "https://10.0.0.9:8443"
    private let lan = "https://192.168.1.1:8443"

    override func setUp() {
        transport = FakeHubTransport()
        clock = FakeClientClock()
        store = BindingStore(secrets: FakeSecretStore())
        left = []
    }

    private func connections() -> HubConnections {
        let connections = HubConnections(
            store: store, transport: transport, machine: Samples.machine, clock: clock,
            resolveHubName: { $0(nil) }, localNetworks: { [] }, hasNetwork: { true },
            onLeaving: { self.left.append($0) })
        connections.start()
        return connections
    }

    private func keepOld() throws {
        var old = Samples.binding
        old.gatewayUrl = oldUrl
        old.gatewayUrls = [oldUrl]
        try store.put(old)
    }

    /// Join the hub at `lan`, spend the ticket for `id`, and take its welcome.
    private func join(_ connections: HubConnections, givenId id: String) throws -> String {
        connections.startJoin(
            Samples.link([
                "urls": .array([.string(lan)]), "token": .string("TICKET"), "fp": .string(Samples.fingerprint),
                "role": .string("client"),
            ]))
        let joined = try XCTUnwrap(connections.join.joinedId)
        let socket = try XCTUnwrap(transport.sockets(to: lan).last)
        socket.deliver(.opened)
        let spend = try XCTUnwrap(transport.posts.last { $0.path == Channel.joinPath })
        spend.completion(.success(["id": .string(id), "token": .string("tok")]))
        socket.deliver(frame: Samples.welcome)
        return joined
    }

    private var leaves: [FakeHubPost] {
        transport.posts.filter { $0.path == Channel.leavePath }
    }

    func testJoiningAgainWithTheSameIdDropsTheOldBindingAndTellsTheHubNothing() throws {
        try keepOld()
        let connections = self.connections()
        let joined = try join(connections, givenId: "b1")
        XCTAssertEqual(store.bindings.map(\.id), [joined])
        XCTAssertEqual(store.get(joined)?.boundId, "b1")
        XCTAssertEqual(left, ["b1"])
        XCTAssertTrue(leaves.isEmpty)
        XCTAssertEqual(connections.views.map(\.binding.id), [joined])
    }

    func testAWelcomeOfANewIdEndsTheOldBindingAndTellsTheHub() throws {
        try keepOld()
        let connections = self.connections()
        let joined = try join(connections, givenId: "c9")
        XCTAssertEqual(store.bindings.map(\.id), [joined])
        XCTAssertEqual(store.get(joined)?.boundId, "c9")
        XCTAssertEqual(store.get(joined)?.hubId, "hub-1")
        XCTAssertEqual(left, ["b1"])
        XCTAssertEqual(leaves.map(\.baseUrl), [oldUrl])
        XCTAssertEqual(leaves.first?.body.text("id"), "b1")
        XCTAssertEqual(connections.views.map(\.binding.id), [joined])
    }

    func testABindingTheHubForgotEndsAtTheWelcomeWhateverTheLeaveAnswers() throws {
        try keepOld()
        let connections = self.connections()
        let old = try XCTUnwrap(transport.sockets(to: oldUrl).first)
        old.deliver(.opened)
        old.deliver(frame: ["type": .string("refused"), "code": .string("binding_unknown")])
        XCTAssertEqual(connections.views.first?.waitReason, .unknownDevice)
        let joined = try join(connections, givenId: "c9")
        try XCTUnwrap(leaves.first).completion(.failure(.refusal("binding_unknown")))
        XCTAssertEqual(store.bindings.map(\.id), [joined])
        XCTAssertEqual(left, ["b1"])
        XCTAssertEqual(leaves.map(\.baseUrl), [oldUrl])
        XCTAssertEqual(connections.views.map(\.binding.id), [joined])
    }

    func testAStartKeepsOneBindingPerHub() throws {
        try store.put(Samples.binding)
        var other = Samples.binding
        other.id = "b2"
        other.hubId = "hub-2"
        try store.put(other)
        var later = Samples.binding
        later.id = "b3"
        later.token = "t3"
        try store.put(later)
        let connections = self.connections()
        XCTAssertEqual(store.bindings.map(\.id), ["b2", "b3"])
        XCTAssertEqual(left, ["b1"])
        XCTAssertEqual(leaves.map { $0.body.text("id") }, ["b1"])
        XCTAssertEqual(connections.views.map(\.binding.id), ["b2", "b3"])
    }
}
