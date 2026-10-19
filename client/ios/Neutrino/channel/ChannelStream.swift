import Foundation

/// One stream this phone opened: its close, and on a byte stream its bytes both ways under credit. Every call
/// runs on the main queue.
final class ChannelStream {
    /// The stream's id, odd.
    let id: UInt32

    /// The stream's kind.
    let kind: String

    private weak var socket: ChannelSocket?
    private let hasBytes: Bool
    private let clock: ClientClock
    private let onClosedHere: (UInt32) -> Void
    private var credit = 0
    private var unconsumed = 0
    private var outgoing: [ChannelStreamSend] = []
    private var creditTimer: ClientTimer?
    private var held: [Data] = []
    private var result: Result<[String: JSONValue], ClientError>?
    private var waiters: [Int: (Result<[String: JSONValue], ClientError>) -> Void] = [:]
    private var nextWaiter = 0

    /// Where the hub's bytes go, in order; bytes that came before it was set are handed to it at once. The
    /// reader calls `consumed(_:)` for every byte it has passed on.
    var onBytes: ((Data) -> Void)? {
        didSet { deliverHeld() }
    }

    /// Called once when the hub ends the stream: nil for a close with no code, the refusal otherwise, and
    /// `hub_unreachable` once the socket ended. A close from this side calls nothing.
    var onEnd: ((ClientError?) -> Void)?

    /// Open a stream's local end; the registry sends the open.
    ///
    /// - Parameters:
    ///   - id: The stream's id.
    ///   - kind: The stream's kind.
    ///   - socket: The socket it runs on.
    ///   - hasBytes: Whether it carries bytes.
    ///   - clock: The timers of the credit wait and the close wait.
    ///   - onClosedHere: Called with the id when this side ends it.
    init(
        id: UInt32, kind: String, socket: ChannelSocket, hasBytes: Bool, clock: ClientClock,
        onClosedHere: @escaping (UInt32) -> Void
    ) {
        self.id = id
        self.kind = kind
        self.socket = socket
        self.hasBytes = hasBytes
        self.clock = clock
        self.onClosedHere = onClosedHere
    }

    /// Whether the hub closed it, the socket ended, or this side closed it.
    var isDone: Bool { result != nil }

    /// The code the stream ended in: the hub's refusal, or `hub_unreachable` once the socket ended; else nil.
    var refusal: ClientError? {
        if case .failure(let error) = result { return error }
        return nil
    }

    /// Call back once the hub has closed the stream.
    ///
    /// - Parameters:
    ///   - timeout: How long to wait, in seconds.
    ///   - completion: Called with the close's params, or its refusal; `hub_unreachable` when the socket ended
    ///     first or nothing came in time.
    func whenClosed(timeout: Double, _ completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void) {
        if let result {
            completion(result)
            return
        }
        let key = nextWaiter
        nextWaiter += 1
        waiters[key] = completion
        clock.schedule(after: timeout) { [weak self] in
            guard let self, let waiter = self.waiters.removeValue(forKey: key) else { return }
            waiter(
                .failure(
                    .refusal(Channel.codeHubUnreachable, ["detail": "the hub did not close the \(self.kind) stream"])))
        }
    }

    /// Note bytes the reader has passed on; half the window passed on grants the hub more.
    ///
    /// - Parameter count: How many bytes.
    func consumed(_ count: Int) {
        unconsumed += count
        guard unconsumed >= Channel.streamCreditBytes / 2, !isDone else { return }
        socket?.send(ChannelFrames.credit(stream: id, bytes: unconsumed))
        unconsumed = 0
    }

    /// Send bytes, no faster than the hub's credit, in frames of at most 64 KiB.
    ///
    /// - Parameters:
    ///   - data: The bytes.
    ///   - completion: Called with true once every byte is sent, false when the stream or the socket ended or
    ///     no credit came in time.
    func send(_ data: Data, completion: ((Bool) -> Void)? = nil) {
        guard hasBytes, !isDone else {
            completion?(false)
            return
        }
        outgoing.append(ChannelStreamSend(data: data, completion: completion))
        pump()
    }

    /// End the stream from this side; the hub sends no close back.
    func close() {
        guard result == nil else { return }
        settle(.success([:]))
        socket?.send(ChannelFrames.close(stream: id))
        onClosedHere(id)
    }

    /// Take bytes the hub sent.
    ///
    /// - Parameter data: The bytes after the stream id.
    func takeBytes(_ data: Data) {
        guard !isDone else { return }
        if let onBytes {
            onBytes(data)
        } else {
            held.append(data)
        }
    }

    /// Take a grant from the hub.
    ///
    /// - Parameter bytes: How many more bytes the hub takes.
    func takeCredit(_ bytes: Int) {
        credit += max(bytes, 0)
        creditTimer?.cancel()
        creditTimer = nil
        pump()
    }

    /// Take the hub's close.
    ///
    /// - Parameters:
    ///   - code: The refusal's code, empty for a result.
    ///   - params: The result, or the refusal's parameters.
    func takeClose(code: String, params: [String: JSONValue]) {
        guard result == nil else { return }
        let ending: ClientError? = code.isEmpty ? nil : .refused(code: code, params: params)
        settle(ending.map { .failure($0) } ?? .success(params))
        onEnd?(ending)
    }

    /// The socket ended under the stream.
    func end() {
        guard result == nil else { return }
        let ending = ClientError.refusal(Channel.codeHubUnreachable, ["detail": "the hub socket closed"])
        settle(.failure(ending))
        onEnd?(ending)
    }

    private func settle(_ outcome: Result<[String: JSONValue], ClientError>) {
        result = outcome
        creditTimer?.cancel()
        creditTimer = nil
        let failed = outgoing
        outgoing = []
        held = []
        let called = waiters
        waiters = [:]
        for send in failed { send.completion?(false) }
        for (_, waiter) in called.sorted(by: { $0.key < $1.key }) { waiter(outcome) }
    }

    private func pump() {
        while !isDone, credit > 0, var first = outgoing.first {
            let size = min(first.data.count - first.offset, Channel.chunkBytes, credit)
            let start = first.data.startIndex + first.offset
            let chunk = first.data.subdata(in: start..<(start + size))
            guard socket?.sendBytes(ChannelFrames.binary(stream: id, bytes: chunk)) == true else {
                end()
                return
            }
            credit -= size
            first.offset += size
            if first.offset >= first.data.count {
                outgoing.removeFirst()
                first.completion?(true)
            } else {
                outgoing[0] = first
            }
        }
        if outgoing.isEmpty || isDone {
            creditTimer?.cancel()
            creditTimer = nil
        } else if creditTimer == nil {
            creditTimer = clock.schedule(after: Channel.creditTimeoutSeconds) { [weak self] in
                self?.creditExpired()
            }
        }
    }

    private func creditExpired() {
        creditTimer = nil
        let failed = outgoing
        outgoing = []
        for send in failed { send.completion?(false) }
    }

    private func deliverHeld() {
        guard let onBytes, !held.isEmpty else { return }
        let waiting = held
        held = []
        for data in waiting { onBytes(data) }
    }
}
