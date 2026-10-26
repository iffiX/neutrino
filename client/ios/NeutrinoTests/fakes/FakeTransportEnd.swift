import Foundation

@testable import Neutrino

/// The transport's end of one local connection in a `FakeTransport`: JSON lines until its first line is read,
/// then, for a stream, records and raw bytes.
final class FakeTransportEnd {
    private let link: TransportLink
    private var buffer = Data()

    /// Called with each line while the connection carries lines.
    var onLine: (([String: JSONValue]) -> Void)?

    /// Whether the connection carries a stream's bytes after its first line.
    var isRaw = false

    /// Every byte the app wrote on the stream after its first line.
    private(set) var received = Data()

    /// Whether the app or the fake ended the connection.
    var isClosed: Bool { link.isClosed }

    /// Take the transport's end of a socket pair.
    ///
    /// - Parameter descriptor: The descriptor, non-blocking.
    init(descriptor: Int32) {
        link = TransportLink(descriptor: descriptor)
    }

    /// Start reading.
    func start() {
        link.onData = { [weak self] data in self?.take(data) }
        link.start()
    }

    /// Accept the stream.
    func accept() {
        link.write(TransportRecord.encode(type: Transport.recordAccept, payload: Data()))
    }

    /// Refuse the stream with a code, then end the connection.
    ///
    /// - Parameters:
    ///   - code: The code.
    ///   - params: Its params.
    func refuse(_ code: String, _ params: [String: JSONValue] = [:]) {
        let close: [String: JSONValue] = ["code": .string(code), "params": .object(params)]
        link.write(TransportRecord.encode(type: Transport.recordClose, payload: Data(close.jsonText.utf8))) {
            [weak self] in self?.link.close()
        }
    }

    /// Write one record.
    ///
    /// - Parameters:
    ///   - type: The record's type.
    ///   - payload: Its bytes.
    func record(_ type: UInt8, _ payload: Data) {
        link.write(TransportRecord.encode(type: type, payload: payload))
    }

    /// Write raw bytes.
    ///
    /// - Parameter data: The bytes.
    func write(_ data: Data) {
        link.write(data)
    }

    /// Write one JSON line.
    ///
    /// - Parameter line: The line.
    func writeLine(_ line: [String: JSONValue]) {
        link.write(Data(line.jsonText.utf8) + Data([0x0A]))
    }

    /// The records the app wrote on the stream so far.
    var records: [TransportRecord] {
        var reader = TransportRecordReader()
        return (try? reader.take(received)) ?? []
    }

    /// End the connection.
    func close() {
        link.close()
    }

    private func take(_ data: Data) {
        guard onLine != nil else {
            received.append(data)
            return
        }
        buffer.append(data)
        while let handler = onLine, let end = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<end]
            buffer = Data(buffer[(end + 1)...])
            if let parsed = (try? JSONValue.parse(Data(line)))?.objectValue { handler(parsed) }
            if isRaw {
                onLine = nil
                received.append(buffer)
                buffer = Data()
                return
            }
        }
    }
}
