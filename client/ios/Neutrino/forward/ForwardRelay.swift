import Foundation

/// One listening loopback port whose every accepted connection is one `connect` stream to the hub. While the
/// hub has no channel the port accepts nothing and stays bound, and the connections waiting in its queue are
/// served once the channel is back. Every call runs on the main queue.
final class ForwardRelay {
    /// What the log calls the far end.
    let name: String

    private let open: () -> Result<TransportStream, ClientError>
    private var descriptor: Int32 = -1
    private var source: DispatchSourceRead?
    private var isSourceSuspended = false
    private var isChannelOpen = true
    private var pipes: [ObjectIdentifier: ForwardPipe] = [:]
    private var endedUp: Int64 = 0
    private var endedDown: Int64 = 0

    /// The loopback number bound; 0 until started.
    private(set) var localPort = 0

    /// Called when the hub refuses a connection's `connect` stream, at its open or by closing it with a code.
    var onRefused: ((ClientError) -> Void)?

    /// Prepare a forward.
    ///
    /// - Parameters:
    ///   - name: What the log calls the far end.
    ///   - open: Opens one `connect` stream for one accepted connection.
    init(name: String, open: @escaping () -> Result<TransportStream, ClientError>) {
        self.name = name
        self.open = open
    }

    /// Whether the relay listens.
    var isActive: Bool { source != nil }

    /// Whether a connection the relay accepted is still open.
    var isCarrying: Bool { !pipes.isEmpty }

    /// The bytes every connection the relay accepted has carried up, from the connection to the hub, so far.
    var bytesUp: Int64 { pipes.values.reduce(endedUp) { $0 + $1.bytesUp } }

    /// The bytes every connection the relay accepted has carried down, from the hub to the connection, so far.
    var bytesDown: Int64 { pipes.values.reduce(endedDown) { $0 + $1.bytesDown } }

    /// Bind the loopback and start accepting.
    ///
    /// - Parameter port: The number to listen on; 0 for any free one.
    /// - Returns: The number bound.
    /// - Throws: `ClientError.refused` with `forward_failed {detail}` when the number cannot be bound.
    @discardableResult
    func start(port: Int) throws -> Int {
        let (descriptor, bound) = try ForwardSocket.listenLoopback(port: port)
        self.descriptor = descriptor
        localPort = bound
        let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: .main)
        source.setEventHandler { [weak self] in self?.acceptWaiting() }
        source.setCancelHandler { ForwardSocket.closeDescriptor(descriptor) }
        self.source = source
        source.resume()
        if !isChannelOpen {
            source.suspend()
            isSourceSuspended = true
        }
        return bound
    }

    /// The hub's channel opened or closed: accepting stops while it is closed and goes on once it opens.
    ///
    /// - Parameter isOpen: Whether the hub has a channel now.
    func channelChanged(isOpen: Bool) {
        isChannelOpen = isOpen
        guard let source else { return }
        if isOpen && isSourceSuspended {
            source.resume()
            isSourceSuspended = false
        } else if !isOpen && !isSourceSuspended {
            source.suspend()
            isSourceSuspended = true
        }
    }

    /// Stop listening and close every open connection; the loopback number is free once the main queue turns.
    func close() {
        if let source {
            source.cancel()
            if isSourceSuspended { source.resume() }
        }
        source = nil
        isSourceSuspended = false
        for pipe in Array(pipes.values) { pipe.shutdown() }
    }

    private func acceptWaiting() {
        while let accepted = ForwardSocket.acceptWaiting(descriptor) {
            switch open() {
            case .failure(let refusal):
                ClientLog.info("a connection to \(name) was not opened: \(refusal.code)")
                onRefused?(refusal)
                ForwardSocket.closeDescriptor(accepted)
            case .success(let stream):
                let pipe = ForwardPipe(descriptor: accepted, stream: stream) { [weak self] pipe in
                    guard let self, self.pipes.removeValue(forKey: ObjectIdentifier(pipe)) != nil else { return }
                    self.endedUp += pipe.bytesUp
                    self.endedDown += pipe.bytesDown
                }
                pipe.onRefused = { [weak self] refusal in self?.onRefused?(refusal) }
                pipes[ObjectIdentifier(pipe)] = pipe
                pipe.start()
            }
        }
    }
}
