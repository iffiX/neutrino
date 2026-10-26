import Foundation

/// Reads records out of a stream's bytes as they come, whatever their cut.
struct TransportRecordReader {
    private var buffer = Data()

    /// The bytes taken and not yet read as a record.
    var rest: Data { buffer }

    /// Take bytes and read every whole record they complete.
    ///
    /// - Parameter data: The next bytes.
    /// - Returns: The records, in order.
    /// - Throws: `ClientError.refused` with `hub_unreachable {detail}` for a length past the largest record.
    mutating func take(_ data: Data) throws -> [TransportRecord] {
        append(data)
        var records: [TransportRecord] = []
        while let record = try next() { records.append(record) }
        return records
    }

    /// Take bytes without reading them yet.
    ///
    /// - Parameter data: The next bytes.
    mutating func append(_ data: Data) {
        buffer.append(data)
    }

    /// Read one whole record, if the bytes hold one.
    ///
    /// - Returns: The record, or nil until its bytes have come.
    /// - Throws: `ClientError.refused` with `hub_unreachable {detail}` for a length past the largest record.
    mutating func next() throws -> TransportRecord? {
        let header = Transport.recordHeaderBytes
        guard buffer.count >= header else { return nil }
        let start = buffer.startIndex
        let length = buffer[(start + 1)..<(start + header)].reduce(0) { $0 << 8 | Int($1) }
        guard length <= Transport.recordBytesMax else {
            throw ClientError.refusal(Channel.codeHubUnreachable, ["detail": "a record of \(length) bytes"])
        }
        guard buffer.count >= header + length else { return nil }
        let record = TransportRecord(
            type: buffer[start], payload: Data(buffer[(start + header)..<(start + header + length)]))
        buffer = Data(buffer[(start + header + length)...])
        return record
    }
}
