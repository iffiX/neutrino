import XCTest

@testable import Neutrino

final class HubConnectionsTests: XCTestCase {
    private var fake = FakeTransport()
    private var clock = FakeClientClock()
    private var store = BindingStore(secrets: FakeSecretStore())
    private var left: [String] = []

    private let lan = "tcp://192.168.1.1:8443"

    override func setUp() {
        fake = FakeTransport()
        clock = FakeClientClock()
        store = BindingStore(secrets: FakeSecretStore())
        left = []
    }

    private func connections() -> HubConnections {
        let transport = ClientTransport(library: fake, directory: "/data", dialerOf: { _ in self.fake }, clock: clock)
        transport.start()
        let connections = HubConnections(
            store: store, transport: transport, machine: Samples.machine, clock: clock,
            resolveHubName: { $0(nil) }, localNetworks: { [] }, hasNetwork: { true },
            onLeaving: { self.left.append($0) })
        connections.start()
        return connections
    }

    private func link(ticket: String = "TICKET") -> EnrollmentLink {
        EnrollmentLink(urls: [lan], ticket: ticket, hubKey: Samples.hubKey, overlays: [])
    }

    func testAJoinKeepsTheBindingWithTheHubsKeyAndAFreshKeyOfItsOwn() throws {
        let connections = self.connections()
        let binding = try connections.keep(link())
        XCTAssertTrue(binding.isPending)
        XCTAssertEqual(binding.hubKey, Samples.hubKey)
        XCTAssertEqual(binding.privateKey.count, 64)
        XCTAssertTrue(binding.privateKey.allSatisfy(\.isHexDigit))
        XCTAssertEqual(try connections.keep(link()), binding)
        XCTAssertNotEqual(try connections.keep(link(ticket: "OTHER")).privateKey, binding.privateKey)
    }

    func testAJoinThatLandsOnAnotherBindingsIdEndsItWithNothingTold() throws {
        var old = Samples.binding
        old.id = "c9"
        try store.put(old)
        fake.answer = { line in
            line.text("command") == "join" ? ["binding_id": .string("c9"), "token": .string("t9")] : [:]
        }
        let connections = self.connections()
        let pending = try connections.keep(link())
        XCTAssertTrue(RunLoopWait.until { self.store.bindings.map(\.id) == [pending.id] })
        XCTAssertEqual(store.get(pending.id)?.boundId, "c9")
        XCTAssertEqual(left, ["c9"])
        RunLoopWait.turn()
        XCTAssertTrue(fake.sent("leave").isEmpty)
    }

    func testAWelcomeNamingAHubAnotherBindingHoldsEndsThatBindingAndTellsTheHub() throws {
        var old = Samples.binding
        old.id = "old"
        try store.put(old)
        var fresh = Samples.binding
        fresh.id = "fresh"
        fresh.hubId = ""
        try store.put(fresh)
        let connections = self.connections()
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("dial").count == 2 })
        fake.event("session_open", "fresh", ["address": .string(lan), "path": .string("lan")])
        XCTAssertTrue(RunLoopWait.until { self.fake.frames.contains { $0.binding == "fresh" } })
        fake.frame("fresh", Samples.welcome)
        XCTAssertTrue(RunLoopWait.until { self.store.bindings.map(\.id) == ["fresh"] })
        XCTAssertEqual(connections.views.map(\.binding.id), ["fresh"])
        XCTAssertEqual(left, ["old"])
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("leave").first?.text("binding") == "old" })
    }

    func testALeaveForgetsTheBindingAtOnceAndTellsTheHubThroughTheTransport() throws {
        try store.put(Samples.binding)
        let connections = self.connections()
        connections.leave("b1")
        XCTAssertNil(store.get("b1"))
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("leave").isEmpty })
        let leave = try XCTUnwrap(fake.sent("leave").first)
        XCTAssertEqual(leave.text("hub_key"), Samples.hubKey)
        XCTAssertEqual(leave.text("psk"), Samples.binding.psk)
        XCTAssertEqual(leave.text("role"), "client")
    }

    func testLeavingAPendingBindingOrOneOf05TellsTheHubNothing() throws {
        var pending = Samples.binding
        pending.ticket = "T"
        try store.put(pending)
        var old = Samples.binding
        old.id = "b2"
        old.hubKey = ""
        try store.put(old)
        let connections = self.connections()
        connections.leave("b1")
        connections.leave("b2")
        XCTAssertTrue(store.bindings.isEmpty)
        RunLoopWait.turn()
        XCTAssertTrue(fake.sent("leave").isEmpty)
    }

    func testAStartKeepsOneBindingPerHubAndTellsTheHubForEachOneEnded() throws {
        var first = Samples.binding
        first.id = "old"
        try store.put(first)
        var second = Samples.binding
        second.id = "new"
        try store.put(second)
        let connections = self.connections()
        XCTAssertEqual(store.bindings.map(\.id), ["new"])
        XCTAssertEqual(connections.views.count, 1)
        XCTAssertEqual(left, ["old"])
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("leave").first?.text("binding") == "old" })
    }
}
