import XCTest

@testable import Neutrino

final class ChannelStreamRegistryTests: XCTestCase {
    private let socket = FakeChannelSocket(url: "https://a:1")
    private let clock = FakeClientClock()

    func testStreamsOpenAtOddIdsAndAByteStreamIsGrantedItsWindow() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let first = try registry.open(kind: "service", args: ["id": .string("x")], hasBytes: false).get()
        let second = try registry.open(kind: "connect", args: ["id": .string("x")], hasBytes: true).get()
        XCTAssertEqual([first.id, second.id], [1, 3])
        XCTAssertEqual(socket.frameTypes, ["open", "open", "credit"])
        XCTAssertEqual(socket.frames.last?.number("bytes"), Channel.streamCreditBytes)
    }

    func testBytesGoUnderTheHubsCreditInChunks() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let stream = try registry.open(kind: "connect", args: [:], hasBytes: true).get()
        var isSent = false
        stream.send(Data(repeating: 7, count: Channel.chunkBytes + 10)) { isSent = $0 }
        XCTAssertTrue(socket.binaries.isEmpty)
        registry.takeCredit(stream: stream.id, bytes: Channel.chunkBytes + 4)
        XCTAssertEqual(socket.binaries.map(\.count), [4 + Channel.chunkBytes, 4 + 4])
        XCTAssertFalse(isSent)
        registry.takeCredit(stream: stream.id, bytes: 100)
        XCTAssertEqual(socket.binaries.map(\.count), [4 + Channel.chunkBytes, 4 + 4, 4 + 6])
        XCTAssertTrue(isSent)
    }

    func testASendWithNoCreditForAMinuteIsDropped() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let stream = try registry.open(kind: "connect", args: [:], hasBytes: true).get()
        var outcome: Bool?
        stream.send(Data([1])) { outcome = $0 }
        clock.advance(by: Channel.creditTimeoutSeconds)
        XCTAssertEqual(outcome, false)
    }

    func testTheHubsBytesReachTheReaderAndHalfTheWindowConsumedGrantsMore() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let stream = try registry.open(kind: "shell", args: [:], hasBytes: true).get()
        var read = Data()
        registry.takeBinary(ChannelFrames.binary(stream: stream.id, bytes: Data([1, 2])))
        stream.onBytes = { read.append($0) }
        XCTAssertEqual(read, Data([1, 2]))
        stream.consumed(Channel.streamCreditBytes / 2)
        XCTAssertEqual(socket.frames.last?.text("type"), "credit")
        XCTAssertEqual(socket.frames.last?.number("bytes"), Channel.streamCreditBytes / 2)
    }

    func testTheHubsCloseIsTheResultAndARefusalItsCode() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let service = try registry.open(kind: "service", args: [:], hasBytes: false).get()
        let refused = try registry.open(kind: "service", args: [:], hasBytes: false).get()
        var results: [Result<[String: JSONValue], ClientError>] = []
        service.whenClosed(timeout: 15) { results.append($0) }
        refused.whenClosed(timeout: 15) { results.append($0) }
        registry.takeClose(stream: service.id, code: "", params: ["token": .string("t")])
        registry.takeClose(stream: refused.id, code: "permission_denied", params: ["kind": .string("panel")])
        XCTAssertEqual(try results[0].get(), ["token": .string("t")])
        XCTAssertEqual(refused.refusal, .refused(code: "permission_denied", params: ["kind": .string("panel")]))
    }

    func testAStreamTheHubNeverClosesTimesOutAndTheSocketsEndEndsEveryStream() throws {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        let first = try registry.open(kind: "service", args: [:], hasBytes: false).get()
        let second = try registry.open(kind: "connect", args: [:], hasBytes: true).get()
        var timedOut: ClientError?
        first.whenClosed(timeout: 15) { result in
            if case .failure(let error) = result { timedOut = error }
        }
        clock.advance(by: 15)
        XCTAssertEqual(timedOut?.code, Channel.codeHubUnreachable)
        var ended: ClientError?
        second.onEnd = { ended = $0 }
        registry.endAll()
        XCTAssertEqual(ended?.code, Channel.codeHubUnreachable)
        XCTAssertThrowsError(try registry.open(kind: "service", args: [:], hasBytes: false).get())
    }

    func testAStreamTheHubOpensIsRefused() {
        let registry = ChannelStreamRegistry(socket: socket, clock: clock)
        registry.refuse(stream: 2, kind: "shell")
        XCTAssertEqual(socket.frames.last?.text("code"), Channel.codeKindUnknown)
        XCTAssertEqual(socket.frames.last?.number("stream"), 2)
    }
}
