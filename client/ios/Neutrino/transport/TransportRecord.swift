import Foundation

/// One record of a stream: `<u8 type><u32 length, big-endian><payload>`.
struct TransportRecord: Equatable {
    /// The record's type, one of `Transport.record*`.
    let type: UInt8

    /// Its bytes.
    let payload: Data

    /// The payload read as one JSON object, empty when it is not one.
    var json: [String: JSONValue] {
        (try? JSONValue.parse(payload))?.objectValue ?? [:]
    }

    /// A `close` record's refusal: its code and params, or nil for a close that carries a result.
    var refusal: ClientError? {
        guard type == Transport.recordClose else { return nil }
        let body = json
        let code = body.text("code")
        return code.isEmpty ? nil : .refused(code: code, params: body.object("params"))
    }

    /// The bytes of one record, cut into as many as the payload needs.
    ///
    /// - Parameters:
    ///   - type: The record's type.
    ///   - payload: Its bytes.
    /// - Returns: The records' bytes.
    static func encode(type: UInt8, payload: Data) -> Data {
        var out = Data()
        var offset = payload.startIndex
        repeat {
            let size = min(payload.endIndex - offset, Transport.recordBytesMax)
            out.append(type)
            withUnsafeBytes(of: UInt32(size).bigEndian) { out.append(contentsOf: $0) }
            out.append(payload[offset..<(offset + size)])
            offset += size
        } while offset < payload.endIndex
        return out
    }
}
