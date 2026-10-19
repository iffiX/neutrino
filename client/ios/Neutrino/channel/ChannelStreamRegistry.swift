import Foundation

/// The streams open on one socket, by id: this side opens odd ids counting up from 1.
final class ChannelStreamRegistry {
    private let socket: ChannelSocket
    private let clock: ClientClock
    private var streams: [UInt32: ChannelStream] = [:]
    private var nextId = Channel.firstStreamId
    private var isEnded = false

    /// Keep the streams of one socket.
    ///
    /// - Parameters:
    ///   - socket: The socket.
    ///   - clock: The timers every stream waits with.
    init(socket: ChannelSocket, clock: ClientClock) {
        self.socket = socket
        self.clock = clock
    }

    /// Open one stream: the next odd id, the open sent, and a byte stream granted a window at once.
    ///
    /// - Parameters:
    ///   - kind: The stream's kind.
    ///   - args: The kind's own arguments.
    ///   - hasBytes: Whether it carries bytes both ways.
    /// - Returns: The stream, or `hub_unreachable` when the socket is gone.
    func open(kind: String, args: [String: JSONValue], hasBytes: Bool) -> Result<ChannelStream, ClientError> {
        let closed = ClientError.refusal(Channel.codeHubUnreachable, ["detail": "the socket is closed"])
        guard !isEnded else { return .failure(closed) }
        let id = nextId
        nextId += Channel.streamIdStep
        let stream = ChannelStream(
            id: id, kind: kind, socket: socket, hasBytes: hasBytes, clock: clock,
            onClosedHere: { [weak self] id in self?.streams[id] = nil })
        streams[id] = stream
        var isSent = socket.send(ChannelFrames.open(stream: id, kind: kind, args: args))
        if isSent && hasBytes {
            isSent = socket.send(ChannelFrames.credit(stream: id, bytes: Channel.streamCreditBytes))
        }
        guard isSent else {
            streams[id] = nil
            return .failure(closed)
        }
        return .success(stream)
    }

    /// Hand one binary frame to its stream.
    ///
    /// - Parameter frame: The frame: a big-endian u32 stream id, then the bytes; a shorter frame is dropped.
    func takeBinary(_ frame: Data) {
        guard frame.count >= Channel.streamIdBytes else { return }
        let head = frame.startIndex
        let id = frame[head..<(head + Channel.streamIdBytes)].reduce(UInt32(0)) { $0 << 8 | UInt32($1) }
        streams[id]?.takeBytes(frame.subdata(in: (head + Channel.streamIdBytes)..<frame.endIndex))
    }

    /// Hand one credit to its stream.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - bytes: The grant.
    func takeCredit(stream: UInt32, bytes: Int) {
        streams[stream]?.takeCredit(bytes)
    }

    /// Hand one close to its stream, which is then forgotten.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - code: The refusal's code, empty for a result.
    ///   - params: The result, or the refusal's parameters.
    func takeClose(stream: UInt32, code: String, params: [String: JSONValue]) {
        streams.removeValue(forKey: stream)?.takeClose(code: code, params: params)
    }

    /// Close a stream the hub opened: a client serves no kind.
    ///
    /// - Parameters:
    ///   - stream: The stream's id.
    ///   - kind: Its kind.
    func refuse(stream: UInt32, kind: String) {
        socket.send(ChannelFrames.close(stream: stream, code: Channel.codeKindUnknown, params: ["kind": .string(kind)]))
    }

    /// The socket ended: every stream on it ends with `hub_unreachable`.
    func endAll() {
        isEnded = true
        let ended = streams.sorted { $0.key < $1.key }.map(\.value)
        streams = [:]
        for stream in ended { stream.end() }
    }
}
