import Foundation

/// One connection to the transport's local socket, read and written on the main queue: what the transport sends
/// goes to `onData` as it comes, and what the app writes is held until the socket takes it.
final class TransportLink {
    private let descriptor: Int32
    private var readSource: DispatchSourceRead?
    private var writeSource: DispatchSourceWrite?
    private var pending = Data()
    private var drained: [() -> Void] = []
    private var openSources = 0

    /// Where the transport's bytes go, in order.
    var onData: ((Data) -> Void)?

    /// Called once when the connection ends, from either side.
    var onEnd: (() -> Void)?

    /// Whether the connection has ended.
    private(set) var isClosed = false

    /// Take a connection.
    ///
    /// - Parameter descriptor: The connection, non-blocking.
    init(descriptor: Int32) {
        self.descriptor = descriptor
    }

    /// Start reading.
    func start() {
        let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: .main)
        source.setEventHandler { [weak self] in self?.readAvailable() }
        source.setCancelHandler { self.sourceCancelled() }
        openSources += 1
        readSource = source
        source.resume()
    }

    /// Write bytes after every byte written before them.
    ///
    /// - Parameters:
    ///   - data: The bytes.
    ///   - onWritten: Called once the socket has taken them and every byte before them.
    /// - Returns: False when the connection has ended.
    @discardableResult
    func write(_ data: Data, onWritten: (() -> Void)? = nil) -> Bool {
        guard !isClosed else { return false }
        pending.append(data)
        if let onWritten { drained.append(onWritten) }
        flush()
        return !isClosed
    }

    /// End the connection from this side; `onEnd` is not called.
    func close() {
        guard !isClosed else { return }
        onEnd = nil
        shut()
    }

    private func readAvailable() {
        guard !isClosed else { return }
        while true {
            let data: Data
            do {
                guard let read = try ForwardSocket.readAvailable(descriptor) else { return }
                data = read
            } catch {
                ended()
                return
            }
            if data.isEmpty {
                ended()
                return
            }
            onData?(data)
            if isClosed { return }
        }
    }

    private func flush() {
        guard !isClosed else { return }
        while !pending.isEmpty {
            let written: Int
            do {
                written = try ForwardSocket.writeAvailable(descriptor, pending)
            } catch {
                ended()
                return
            }
            if written == 0 { break }
            pending.removeFirst(written)
        }
        if pending.isEmpty {
            writeSource?.cancel()
            writeSource = nil
            let waiting = drained
            drained = []
            for call in waiting { call() }
        } else if writeSource == nil {
            let source = DispatchSource.makeWriteSource(fileDescriptor: descriptor, queue: .main)
            source.setEventHandler { [weak self] in self?.flush() }
            source.setCancelHandler { self.sourceCancelled() }
            openSources += 1
            writeSource = source
            source.resume()
        }
    }

    private func ended() {
        guard !isClosed else { return }
        let call = onEnd
        onEnd = nil
        shut()
        call?()
    }

    private func shut() {
        isClosed = true
        pending = Data()
        drained = []
        readSource?.cancel()
        readSource = nil
        writeSource?.cancel()
        writeSource = nil
        if openSources == 0 { ForwardSocket.closeDescriptor(descriptor) }
    }

    private func sourceCancelled() {
        openSources -= 1
        if isClosed && openSources == 0 { ForwardSocket.closeDescriptor(descriptor) }
    }
}
