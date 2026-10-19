import Foundation

/// One listening loopback port whose every accepted connection is one `connect` stream to the hub. While the
/// hub has no channel the port accepts nothing and stays bound, and the connections waiting in its queue are
/// served once the channel is back. Every call runs on the main queue.
final class ForwardRelay {
    /// What the log calls the far end.
    let name: String

    private let open: () -> Result<ChannelStream, ClientError>
    private var descriptor: Int32 = -1
    private var source: DispatchSourceRead?
    private var isSourceSuspended = false
    private var isChannelOpen = true
    private var pipes: [ObjectIdentifier: ForwardPipe] = [:]

    /// The loopback number bound; 0 until started.
    private(set) var localPort = 0

    /// Prepare a forward.
    ///
    /// - Parameters:
    ///   - name: What the log calls the far end.
    ///   - open: Opens one `connect` stream for one accepted connection.
    init(name: String, open: @escaping () -> Result<ChannelStream, ClientError>) {
        self.name = name
        self.open = open
    }

    /// Whether the relay listens.
    var isActive: Bool { source != nil }

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
                ForwardSocket.closeDescriptor(accepted)
            case .success(let stream):
                let pipe = ForwardPipe(descriptor: accepted, stream: stream) { [weak self] pipe in
                    self?.pipes[ObjectIdentifier(pipe)] = nil
                }
                pipes[ObjectIdentifier(pipe)] = pipe
                pipe.start()
            }
        }
    }
}
