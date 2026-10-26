import XCTest

@testable import Neutrino

final class TransportRecordTests: XCTestCase {
    func testARecordIsItsTypeItsBigEndianLengthAndItsPayload() {
        XCTAssertEqual(
            TransportRecord.encode(type: Transport.recordData, payload: Data([7, 8])), Data([3, 0, 0, 0, 2, 7, 8]))
    }

    func testAPayloadPastTheLargestRecordIsCutIntoSeveral() throws {
        let bytes = TransportRecord.encode(
            type: Transport.recordData, payload: Data(repeating: 1, count: Transport.recordBytesMax + 3))
        var reader = TransportRecordReader()
        let records = try reader.take(bytes)
        XCTAssertEqual(records.map(\.payload.count), [Transport.recordBytesMax, 3])
    }

    func testRecordsAreReadWhateverTheirBytesCut() throws {
        let bytes =
            TransportRecord.encode(type: Transport.recordAccept, payload: Data())
            + TransportRecord.encode(type: Transport.recordData, payload: Data("hello".utf8))
        var reader = TransportRecordReader()
        var records: [TransportRecord] = []
        for byte in bytes { records += try reader.take(Data([byte])) }
        XCTAssertEqual(records.map(\.type), [Transport.recordAccept, Transport.recordData])
        XCTAssertEqual(records.last?.payload, Data("hello".utf8))
        XCTAssertTrue(reader.rest.isEmpty)
    }

    func testACloseWithACodeIsARefusalAndOneWithoutIsAResult() {
        let refused = TransportRecord(
            type: Transport.recordClose, payload: Data(#"{"code":"agent_offline","params":{"device":"d1"}}"#.utf8))
        XCTAssertEqual(refused.refusal?.code, "agent_offline")
        XCTAssertEqual(refused.refusal?.wordParams["device"], "d1")
        let result = TransportRecord(type: Transport.recordClose, payload: Data(#"{"code":"","params":{}}"#.utf8))
        XCTAssertNil(result.refusal)
    }
}
