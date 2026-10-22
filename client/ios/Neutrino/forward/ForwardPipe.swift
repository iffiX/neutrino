import Foundation

/// One accepted loopback connection joined to one `connect` stream: the bytes are copied both ways, the hub's
/// under its credit and the connection's as it takes them. The end of either side closes the stream once what
/// was read from that side is sent, and the side that ends second writes what it holds and closes. Every call
/// runs on the main queue.
final class ForwardPipe {
    private let descriptor: Int32
    private let stream: ChannelStream
    private let onEnd: (ForwardPipe) -> Void
    private var readSource: DispatchSourceRead?
    private var writeSource: DispatchSourceWrite?
    private var isReadSuspended = false
    private var pending = Data()
    private var sendsInFlight = 0
    private var isLocalEnded = false
    private var isHubEnded = false
    private var isShut = false
    private var openSources = 0

    /// Called when the hub ends the stream with a code.
    var onRefused: ((ClientError) -> Void)?

    /// The bytes carried up so far: read from the connection and sent on the stream.
    private(set) var bytesUp: Int64 = 0

    /// The bytes carried down so far: taken from the stream and written to the connection.
    private(set) var bytesDown: Int64 = 0

    /// Join a connection to a stream.
    ///
    /// - Parameters:
    ///   - descriptor: The accepted connection, non-blocking.
    ///   - stream: The `connect` stream for it.
    ///   - onEnd: Called once both are closed.
    init(descriptor: Int32, stream: ChannelStream, onEnd: @escaping (ForwardPipe) -> Void) {
        self.descriptor = descriptor
        self.stream = stream
        self.onEnd = onEnd
    }

    /// Start copying.
    func start() {
        stream.onEnd = { [weak self] ending in self?.hubEnded(ending) }
        stream.onBytes = { [weak self] data in self?.takeFromHub(data) }
        let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: .main)
        source.setEventHandler { [weak self] in self?.readLocal() }
        source.setCancelHandler { self.sourceCancelled() }
        openSources += 1
        readSource = source
        source.resume()
    }

    /// Close the connection and the stream now.
    func shutdown() {
        guard !isShut else { return }
        isShut = true
        stream.onBytes = nil
        stream.onEnd = nil
        stream.close()
        if let readSource {
            readSource.cancel()
            if isReadSuspended { readSource.resume() }
        }
        readSource = nil
        writeSource?.cancel()
        writeSource = nil
        if openSources == 0 { finish() }
    }

    private func readLocal() {
        guard !isShut, !isLocalEnded else { return }
        let data: Data
        do {
            guard let read = try ForwardSocket.readAvailable(descriptor) else { return }
            data = read
        } catch {
            shutdown()
            return
        }
        if data.isEmpty {
            isLocalEnded = true
            suspendRead()
            if sendsInFlight == 0 { shutdown() }
            return
        }
        suspendRead()
        sendsInFlight += 1
        stream.send(data) { [weak self] isSent in
            guard let self, !self.isShut else { return }
            self.sendsInFlight -= 1
            if isSent { self.bytesUp += Int64(data.count) }
            if !isSent || (self.isLocalEnded && self.sendsInFlight == 0) {
                self.shutdown()
            } else if !self.isLocalEnded {
                self.resumeRead()
            }
        }
    }

    private func takeFromHub(_ data: Data) {
        guard !isShut else { return }
        pending.append(data)
        flush()
    }

    private func flush() {
        guard !isShut else { return }
        while !pending.isEmpty {
            let written: Int
            do {
                written = try ForwardSocket.writeAvailable(descriptor, pending)
            } catch {
                shutdown()
                return
            }
            if written == 0 { break }
            pending.removeFirst(written)
            bytesDown += Int64(written)
            stream.consumed(written)
        }
        if pending.isEmpty {
            writeSource?.cancel()
            writeSource = nil
            if isHubEnded { shutdown() }
        } else if writeSource == nil {
            let source = DispatchSource.makeWriteSource(fileDescriptor: descriptor, queue: .main)
            source.setEventHandler { [weak self] in self?.flush() }
            source.setCancelHandler { self.sourceCancelled() }
            openSources += 1
            writeSource = source
            source.resume()
        }
    }

    private func hubEnded(_ ending: ClientError?) {
        if let ending { onRefused?(ending) }
        isHubEnded = true
        if pending.isEmpty { shutdown() }
    }

    private func suspendRead() {
        guard let readSource, !isReadSuspended else { return }
        readSource.suspend()
        isReadSuspended = true
    }

    private func resumeRead() {
        guard let readSource, isReadSuspended else { return }
        readSource.resume()
        isReadSuspended = false
    }

    private func sourceCancelled() {
        openSources -= 1
        if isShut && openSources == 0 { finish() }
    }

    private func finish() {
        ForwardSocket.closeDescriptor(descriptor)
        onEnd(self)
    }
}
