import XCTest

@testable import Neutrino

final class TransportLocalForwarderTests: XCTestCase {
    private var fake = FakeTransport()
    private let open: [String: JSONValue] = ["kind": .string("connect"), "id": .string("gitea_d1_web")]

    override func setUp() {
        fake = FakeTransport()
    }

    private func forwarder() -> TransportLocalForwarder {
        let transport = ClientTransport(
            library: fake, directory: "/data", dialerOf: { _ in self.fake }, clock: FakeClientClock())
        transport.start()
        return TransportLocalForwarder(transport: transport)
    }

    func testABrowserForwardListensOnBothLoopbacksAtOneNumber() {
        fake.answer = { command in ["listen": .string(command.text("listen"))] }
        let forwarder = forwarder()
        var started: Result<Int, ClientError>?
        forwarder.start(bindingId: "b1", port: 27311, protocol: "tcp", open: open, isBrowserOpened: true) {
            started = $0
        }
        XCTAssertTrue(RunLoopWait.until { started != nil })
        XCTAssertEqual(try started?.get(), 27311)
        XCTAssertEqual(fake.sent("forward_start").map { $0.text("listen") }, ["127.0.0.1:27311", "[::1]:27311"])
        forwarder.stop(port: 27311, protocol: "tcp", isBrowserOpened: true)
        XCTAssertTrue(RunLoopWait.until { self.fake.sent("forward_stop").count == 2 })
        XCTAssertEqual(fake.sent("forward_stop").map { $0.text("listen") }, ["127.0.0.1:27311", "[::1]:27311"])
    }

    func testAPortEntrysForwardListensOnOneLoopback() {
        fake.answer = { command in ["listen": .string(command.text("listen"))] }
        let forwarder = forwarder()
        var started: Result<Int, ClientError>?
        forwarder.start(bindingId: "b1", port: 30418, protocol: "tcp", open: open, isBrowserOpened: false) {
            started = $0
        }
        XCTAssertTrue(RunLoopWait.until { started != nil })
        XCTAssertEqual(fake.sent("forward_start").map { $0.text("listen") }, ["127.0.0.1:30418"])
    }

    func testAHeldSecondLoopbackIsPortTakenAndClosesTheFirst() {
        fake.answer = { command in
            let listen = command.text("listen")
            if command.text("command") == "forward_start" && listen.hasPrefix("[::1]") {
                return ["code": .string("port_taken"), "params": .object(["port": .int(27311)])]
            }
            return ["listen": .string(listen)]
        }
        let forwarder = forwarder()
        var started: Result<Int, ClientError>?
        forwarder.start(bindingId: "b1", port: 27311, protocol: "tcp", open: open, isBrowserOpened: true) {
            started = $0
        }
        XCTAssertTrue(RunLoopWait.until { started != nil })
        guard case .failure(let refusal) = started else { return XCTFail("the forward started") }
        XCTAssertEqual(refusal.code, "port_taken")
        XCTAssertTrue(RunLoopWait.until { !self.fake.sent("forward_stop").isEmpty })
        XCTAssertEqual(fake.sent("forward_stop").map { $0.text("listen") }, ["127.0.0.1:27311"])
    }
}
