import XCTest

@testable import Neutrino

final class ClientTransportTests: XCTestCase {
    private var fake = FakeTransport()
    private var clock = FakeClientClock()

    override func setUp() {
        fake = FakeTransport()
        clock = FakeClientClock()
    }

    private func started() -> ClientTransport {
        let transport = ClientTransport(library: fake, directory: "/data", dialerOf: { _ in self.fake }, clock: clock)
        transport.start()
        return transport
    }

    func testTheLibraryStartsWithAFreshSecretAndACommandIsAnswered() {
        let transport = started()
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("round", ["binding": .string("b1")]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        XCTAssertEqual(fake.secret.count, 64)
        XCTAssertTrue(fake.secret.allSatisfy(\.isHexDigit))
        XCTAssertEqual(fake.sent("round").first?.text("binding"), "b1")
        if case .failure = answer { XCTFail("the command was refused") }
    }

    func testAnAnswerWithACodeIsTheRefusal() {
        fake.answer = { _ in ["code": .string("port_taken"), "params": .object(["port": .int(24001)])] }
        let transport = started()
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("forward_start", [:]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        guard case .failure(let refusal) = answer else { return XCTFail("the command was taken") }
        XCTAssertEqual(refusal.code, "port_taken")
        XCTAssertEqual(refusal.wordParams["port"], "24001")
    }

    func testACommandThatGetsNoAnswerIsUnreachableAtItsTimeout() {
        fake.answer = { _ in nil }
        let transport = started()
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("dial", [:]) { answer = $0 }
        RunLoopWait.turn()
        clock.advance(by: Transport.commandTimeoutSeconds)
        guard case .failure(let refusal) = answer else { return XCTFail("the command was answered") }
        XCTAssertEqual(refusal.code, Channel.codeHubUnreachable)
    }

    func testEachHubsEventsAndFramesReachItsOwnHandlerInOrder() {
        let transport = started()
        var first: [TransportEvent] = []
        var second: [TransportEvent] = []
        transport.subscribe("b1") { first.append($0) }
        transport.subscribe("b2") { second.append($0) }
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("round", [:]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        fake.event(
            "session_open", "b1",
            ["address": .string("tcp://192.168.1.1:8443"), "path": .string("lan"), "handshake_ms": .int(3)])
        fake.event("round_end", "b2", ["code": .string("hub_unreachable"), "next_round_s": .int(10)])
        fake.frame("b1", ["type": .string("pong"), "nonce": .string("n")])
        XCTAssertTrue(RunLoopWait.until { first.count == 2 && second.count == 1 })
        XCTAssertEqual(first[0], .sessionOpen(address: "tcp://192.168.1.1:8443", path: "lan", handshakeMs: 3))
        XCTAssertEqual(first[1], .frame(["type": .string("pong"), "nonce": .string("n")]))
        XCTAssertEqual(second[0], .roundEnd(.refusal("hub_unreachable"), nextRoundSeconds: 10))
    }

    func testAFrameLineNamesItsBinding() {
        let transport = started()
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("round", [:]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        XCTAssertTrue(transport.frame("b1", ["type": .string("ping"), "nonce": .string("n")]))
        XCTAssertTrue(RunLoopWait.until { !self.fake.frames.isEmpty })
        XCTAssertEqual(fake.frames.first?.binding, "b1")
        XCTAssertEqual(fake.frames.first?.frame.text("type"), "ping")
    }

    func testAControlConnectionThatDropsOpensAgainAndEveryHubDialsAgain() {
        let transport = started()
        var events: [TransportEvent] = []
        transport.subscribe("b1") { events.append($0) }
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("round", [:]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        fake.dropControl()
        RunLoopWait.turn()
        clock.advance(by: Transport.reconnectSeconds)
        XCTAssertTrue(RunLoopWait.until { events == [.restarted] })
    }

    func testABuildWithNoLibraryRefusesAll() {
        fake.isMissing = true
        let transport = started()
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("dial", [:]) { answer = $0 }
        guard case .failure(let refusal) = answer else { return XCTFail("the command went") }
        XCTAssertEqual(refusal.code, Transport.codeMissing)
        guard case .failure(let opened) = transport.open("b1", open: [:], carriage: .raw) else {
            return XCTFail("the stream opened")
        }
        XCTAssertEqual(opened.code, Transport.codeMissing)
    }

    func testAForwardEndIsPassedOnWithItsProtocol() {
        let transport = started()
        var ends: [TransportForwardEnd] = []
        transport.onForwardEnd = { ends.append($0) }
        var answer: Result<[String: JSONValue], ClientError>?
        transport.command("round", [:]) { answer = $0 }
        XCTAssertTrue(RunLoopWait.until { answer != nil })
        fake.send([
            "event": .string("forward_end"), "listen": .string("127.0.0.1:25001"), "protocol": .string("udp"),
            "code": .string("agent_offline"), "params": .object(["device": .string("lab")]),
        ])
        XCTAssertTrue(RunLoopWait.until { !ends.isEmpty })
        XCTAssertEqual(ends.first?.listen, "127.0.0.1:25001")
        XCTAssertEqual(ends.first?.protocol, "udp")
        XCTAssertEqual(ends.first?.refusal?.code, "agent_offline")
    }
}
