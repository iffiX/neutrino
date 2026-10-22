import XCTest

@testable import Neutrino

final class ForwardPipeTests: XCTestCase {
    private let socket = FakeChannelSocket(url: "https://192.168.1.1:8443")
    private let clock = FakeClientClock()

    private func turnMainQueue() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }

    func testTheBytesAConnectionCarriesUpAndDownAreCountedAndKeptAfterItEnds() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let relay = ForwardRelay(name: "b1/music") {
            registry.open(kind: Channel.kindConnect, args: ["id": .string("music")], hasBytes: true)
        }
        let port = try relay.start(port: 0)
        let client = try XCTUnwrap(LoopbackClient(port: port))
        turnMainQueue()
        let open = try XCTUnwrap(socket.frames.first { $0.text("type") == "open" })
        let stream = try XCTUnwrap(open.number("stream").map(UInt32.init))

        client.write(Data("hello".utf8))
        turnMainQueue()
        XCTAssertEqual(relay.bytesUp, 0)
        registry.takeCredit(stream: stream, bytes: 1000)
        XCTAssertEqual(relay.bytesUp, 5)

        registry.takeBinary(ChannelFrames.binary(stream: stream, bytes: Data("world!".utf8)))
        turnMainQueue()
        XCTAssertEqual(client.read(), Data("world!".utf8))
        XCTAssertEqual(relay.bytesDown, 6)

        relay.close()
        turnMainQueue()
        XCTAssertFalse(relay.isCarrying)
        XCTAssertEqual(relay.bytesUp, 5)
        XCTAssertEqual(relay.bytesDown, 6)
    }
}
