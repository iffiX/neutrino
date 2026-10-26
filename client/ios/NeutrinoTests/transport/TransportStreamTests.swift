import XCTest

@testable import Neutrino

final class TransportStreamTests: XCTestCase {
    private var transport = FakeTransport()
    private let open: [String: JSONValue] = ["kind": .string("connect"), "id": .string("gitea_d1_web")]

    override func setUp() {
        transport = FakeTransport()
        _ = try? transport.start(directory: "/data", secret: String(repeating: "ff", count: 32))
    }

    private func opened(_ carriage: TransportStream.Carriage) throws -> TransportStream {
        try TransportStream.open(
            dialer: transport, secret: transport.secret, binding: "b1", open: open, carriage: carriage)
    }

    func testAnOpenNamesItsBindingAndItsOpenRecord() throws {
        _ = try opened(.raw)
        XCTAssertTrue(RunLoopWait.until { !self.transport.streams.isEmpty })
        XCTAssertEqual(transport.streams.first?.open, open)
    }

    func testBytesSentBeforeTheAcceptAreHeldAndThenCarriedRaw() throws {
        transport.serve = { _, _ in }
        let stream = try opened(.raw)
        var down = Data()
        stream.onBytes = { down.append($0) }
        stream.send(Data("hello".utf8))
        XCTAssertTrue(RunLoopWait.until { !self.transport.streams.isEmpty })
        let end = try XCTUnwrap(transport.streams.first?.end)
        RunLoopWait.turn()
        XCTAssertTrue(end.received.isEmpty)
        end.accept()
        end.write(Data("world".utf8))
        XCTAssertTrue(RunLoopWait.until { end.received == Data("hello".utf8) && down == Data("world".utf8) })
    }

    func testARefusingCloseEndsTheStreamWithItsCode() throws {
        transport.serve = { _, end in end.refuse("permission_denied", ["kind": .string("web")]) }
        let stream = try opened(.raw)
        var ending: ClientError??
        stream.onEnd = { ending = .some($0) }
        XCTAssertTrue(RunLoopWait.until { ending != nil })
        XCTAssertEqual(ending??.code, "permission_denied")
        XCTAssertTrue(stream.isDone)
    }

    func testARecordStreamSendsDataRecordsAndEndsAtItsClose() throws {
        let stream = try opened(.records)
        var down = Data()
        var ending: ClientError??
        stream.onBytes = { down.append($0) }
        stream.onEnd = { ending = .some($0) }
        stream.send(Data("ls\n".utf8))
        stream.sendRecord(type: Transport.recordResize, payload: Data(#"{"cols":80,"rows":24}"#.utf8))
        XCTAssertTrue(RunLoopWait.until { (self.transport.streams.first?.end.records.count ?? 0) == 2 })
        let end = try XCTUnwrap(transport.streams.first?.end)
        XCTAssertEqual(end.records.map(\.type), [Transport.recordData, Transport.recordResize])
        end.record(Transport.recordData, Data("$ ".utf8))
        end.record(Transport.recordClose, Data(#"{"code":"","params":{"exit_code":0}}"#.utf8))
        XCTAssertTrue(RunLoopWait.until { ending != nil })
        XCTAssertEqual(down, Data("$ ".utf8))
        XCTAssertNil(ending ?? nil)
        XCTAssertEqual(stream.result["exit_code"]?.intValue, 0)
    }

    func testARecordStreamThatDropsEndsUnreachable() throws {
        let stream = try opened(.records)
        var ending: ClientError??
        stream.onEnd = { ending = .some($0) }
        XCTAssertTrue(RunLoopWait.until { !self.transport.streams.isEmpty })
        RunLoopWait.turn()
        transport.streams.first?.end.close()
        XCTAssertTrue(RunLoopWait.until { ending != nil })
        XCTAssertEqual(ending??.code, Channel.codeHubUnreachable)
    }
}
