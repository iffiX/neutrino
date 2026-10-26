import Foundation

/// One stream this app opened on a hub's session, carried by a local connection of its own. Until the hub's
/// `accept` comes, what the app sends is held; a refusing `close` in its place ends the stream with the refusal.
/// After the `accept`, a TCP `connect` stream carries its connection's raw bytes both ways, and any other stream
/// carries records: its `data` records are its bytes, and its `close` record ends it. Every call runs on the main
/// queue.
final class TransportStream {
    /// What the stream carries after its `accept`.
    enum Carriage {
        /// The raw bytes of one TCP connection.
        case raw
        /// Records: `data` both ways, `resize` up, `close` down.
        case records
    }

    /// The stream's kind.
    let kind: String

    private let link: TransportLink
    private let carriage: Carriage
    private var reader = TransportRecordReader()
    private var isAccepted = false
    private var held: [(Data, ((Bool) -> Void)?)] = []
    private var heldDown: [Data] = []
    private var ending: ClientError??

    /// Where the hub's bytes go, in order; bytes that came before it was set are handed to it at once.
    var onBytes: ((Data) -> Void)? {
        didSet { deliverHeld() }
    }

    /// Called once when the stream ends from the hub's side: nil for a close with no code or the end of a
    /// `connect` stream's bytes, the refusal otherwise, `hub_unreachable` for a record stream that ended with no
    /// close. A close from this side calls nothing.
    var onEnd: ((ClientError?) -> Void)?

    /// The params of a `close` that carried a result, once the stream ended with one.
    private(set) var result: [String: JSONValue] = [:]

    /// Whether the stream has ended, from either side.
    var isDone: Bool { ending != nil }

    private init(kind: String, link: TransportLink, carriage: Carriage) {
        self.kind = kind
        self.link = link
        self.carriage = carriage
    }

    /// Open one stream on a hub's session: the line that names it goes at once, and the hub's answer comes later.
    ///
    /// - Parameters:
    ///   - dialer: Opens the local connection.
    ///   - secret: The transport's secret.
    ///   - binding: The hub, by the name its `dial` gave.
    ///   - open: The stream's `open` record, `{kind, ...args}`.
    ///   - carriage: What it carries after its `accept`.
    /// - Returns: The stream.
    /// - Throws: `ClientError.refused` with `hub_unreachable {detail}` when the transport cannot be reached.
    static func open(
        dialer: TransportDialer, secret: String, binding: String, open: [String: JSONValue], carriage: Carriage
    ) throws -> TransportStream {
        let link = TransportLink(descriptor: try dialer.dial())
        let stream = TransportStream(kind: open.text("kind"), link: link, carriage: carriage)
        link.onData = { [weak stream] data in stream?.take(data) }
        link.onEnd = { [weak stream] in stream?.linkEnded() }
        link.start()
        let first: [String: JSONValue] = [
            "secret": .string(secret), "op": .string("open"), "binding": .string(binding), "open": .object(open),
        ]
        link.write(Data((first.jsonText + "\n").utf8))
        return stream
    }

    /// Send bytes after every byte sent before them: raw on a `connect` stream, else as `data` records. Bytes sent
    /// before the hub's `accept` are held until it comes.
    ///
    /// - Parameters:
    ///   - data: The bytes.
    ///   - completion: Called with true once the transport has taken them, false when the stream ended first.
    func send(_ data: Data, completion: ((Bool) -> Void)? = nil) {
        let bytes = carriage == .raw ? data : TransportRecord.encode(type: Transport.recordData, payload: data)
        write(bytes, completion: completion)
    }

    /// Send one record other than `data`, such as a terminal's `resize`; one sent before the hub's `accept` is
    /// held until it comes.
    ///
    /// - Parameters:
    ///   - type: The record's type.
    ///   - payload: Its bytes.
    func sendRecord(type: UInt8, payload: Data) {
        guard carriage == .records else { return }
        write(TransportRecord.encode(type: type, payload: payload), completion: nil)
    }

    /// End the stream from this side.
    func close() {
        guard !isDone else { return }
        ending = .some(nil)
        failHeld()
        onBytes = nil
        onEnd = nil
        link.close()
    }

    private func write(_ bytes: Data, completion: ((Bool) -> Void)?) {
        guard !isDone else {
            completion?(false)
            return
        }
        guard isAccepted else {
            held.append((bytes, completion))
            return
        }
        let isTaken = link.write(bytes) { completion?(true) }
        if !isTaken { completion?(false) }
    }

    private func take(_ data: Data) {
        guard !isDone else { return }
        if isAccepted && carriage == .raw {
            down(data)
            return
        }
        reader.append(data)
        do {
            while !isDone, let record = try reader.next() {
                takeRecord(record)
                if isAccepted && carriage == .raw {
                    let rest = reader.rest
                    reader = TransportRecordReader()
                    if !rest.isEmpty { down(rest) }
                    return
                }
            }
        } catch let refusal as ClientError {
            end(refusal)
        } catch {
            end(.refusal(Channel.codeHubUnreachable, ["detail": "\(error)"]))
        }
    }

    private func takeRecord(_ record: TransportRecord) {
        if !isAccepted {
            if record.type == Transport.recordAccept {
                isAccepted = true
                let waiting = held
                held = []
                for (bytes, completion) in waiting { write(bytes, completion: completion) }
            } else if record.type == Transport.recordClose {
                end(record.refusal ?? .refusal(Channel.codeHubUnreachable, ["detail": "the stream closed at once"]))
            }
            return
        }
        switch record.type {
        case Transport.recordData:
            down(record.payload)
        case Transport.recordClose:
            if record.refusal == nil { result = record.json.object("params") }
            end(record.refusal)
        default:
            break
        }
    }

    private func down(_ data: Data) {
        if let onBytes {
            onBytes(data)
        } else {
            heldDown.append(data)
        }
    }

    private func linkEnded() {
        guard !isDone else { return }
        if isAccepted && carriage == .raw {
            end(nil)
        } else if isAccepted {
            end(.refusal(Channel.codeHubUnreachable, ["detail": "the stream ended with no close"]))
        } else {
            end(.refusal(Channel.codeHubUnreachable, ["detail": "the stream was not accepted"]))
        }
    }

    private func end(_ refusal: ClientError?) {
        guard !isDone else { return }
        ending = .some(refusal)
        link.close()
        let call = onEnd
        onEnd = nil
        call?(refusal)
        failHeld()
    }

    private func failHeld() {
        let waiting = held
        held = []
        for (_, completion) in waiting { completion?(false) }
    }

    private func deliverHeld() {
        guard let onBytes, !heldDown.isEmpty else { return }
        let waiting = heldDown
        heldDown = []
        for data in waiting { onBytes(data) }
    }
}
