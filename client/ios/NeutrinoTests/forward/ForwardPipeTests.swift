import XCTest

@testable import Neutrino

final class ForwardPipeTests: XCTestCase {
    func testTheBytesAConnectionCarriesUpAndDownAreCountedAndKeptAfterItEnds() throws {
        let transport = FakeTransport()
        _ = try transport.start(directory: "/data", secret: String(repeating: "ee", count: 32))
        let relay = ForwardRelay(name: "b1/music") {
            do {
                return .success(
                    try TransportStream.open(
                        dialer: transport, secret: transport.secret, binding: "b1",
                        open: ["kind": .string(Channel.kindConnect), "id": .string("music")], carriage: .raw))
            } catch {
                return .failure(.refusal(Channel.codeHubUnreachable))
            }
        }
        let port = try relay.start(port: 0)
        let client = try XCTUnwrap(LoopbackClient(port: port))
        XCTAssertTrue(RunLoopWait.until { !transport.streams.isEmpty })
        let end = try XCTUnwrap(transport.streams.first?.end)
        XCTAssertEqual(transport.streams.first?.open.text("id"), "music")

        client.write(Data("hello".utf8))
        XCTAssertTrue(RunLoopWait.until { end.received == Data("hello".utf8) && relay.bytesUp == 5 })

        end.write(Data("world!".utf8))
        RunLoopWait.turn()
        XCTAssertEqual(client.read(), Data("world!".utf8))
        XCTAssertEqual(relay.bytesDown, 6)

        relay.close()
        XCTAssertTrue(RunLoopWait.until { !relay.isCarrying })
        XCTAssertEqual(relay.bytesUp, 5)
        XCTAssertEqual(relay.bytesDown, 6)
    }

    func testAConnectionTheHubRefusesIsClosedAndItsCodeReported() throws {
        let transport = FakeTransport()
        _ = try transport.start(directory: "/data", secret: String(repeating: "ee", count: 32))
        transport.serve = { _, end in end.refuse("permission_denied", ["kind": .string("file")]) }
        var refusals: [ClientError] = []
        let relay = ForwardRelay(name: "b1/music") {
            do {
                return .success(
                    try TransportStream.open(
                        dialer: transport, secret: transport.secret, binding: "b1",
                        open: ["kind": .string(Channel.kindConnect), "id": .string("music")], carriage: .raw))
            } catch {
                return .failure(.refusal(Channel.codeHubUnreachable))
            }
        }
        relay.onRefused = { refusals.append($0) }
        let port = try relay.start(port: 0)
        let client = try XCTUnwrap(LoopbackClient(port: port))
        client.write(Data("hello".utf8))
        XCTAssertTrue(RunLoopWait.until { !refusals.isEmpty })
        XCTAssertEqual(refusals.first?.code, "permission_denied")
        XCTAssertTrue(RunLoopWait.until { !relay.isCarrying })
    }
}
