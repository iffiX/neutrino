import Foundation

/// The client's end of the transport's local channel: the library started in the app's process, its one control
/// connection with the commands, the events and the frames of every hub, and the streams opened each on a
/// connection of its own. A control connection that drops is opened again, and every hub is then told `restarted`
/// so it dials again. Every call runs on the main queue.
final class ClientTransport {
    private let library: TransportLibrary
    private let directory: String
    private let dialerOf: (String) -> TransportDialer
    private let clock: ClientClock
    private let secret: String
    private var dialer: TransportDialer?
    private var failure: ClientError?
    private var control: TransportLink?
    private var buffer = Data()
    private var waiting: [Data] = []
    private var answers: [String: (Result<[String: JSONValue], ClientError>) -> Void] = [:]
    private var handlers: [String: (TransportEvent) -> Void] = [:]
    private var nextId = 0
    private var isStarted = false
    private var hasOpened = false
    private var retry: ClientTimer?

    /// Called with every forward's listener the transport ended.
    var onForwardEnd: ((TransportForwardEnd) -> Void)?

    /// Prepare the transport.
    ///
    /// - Parameters:
    ///   - library: The transport the app embeds.
    ///   - directory: The app's own data directory, where the library makes its local socket.
    ///   - dialerOf: Opens connections to the local socket at the path the library started on.
    ///   - clock: The timers of the commands and of the reconnect.
    ///   - secret: The 64 hex characters every local connection opens with, made afresh at each start.
    init(
        library: TransportLibrary, directory: String, dialerOf: @escaping (String) -> TransportDialer,
        clock: ClientClock, secret: String = ClientTransport.freshSecret()
    ) {
        self.library = library
        self.directory = directory
        self.dialerOf = dialerOf
        self.clock = clock
        self.secret = secret
    }

    /// Start the library and open its control connection.
    func start() {
        guard !isStarted else { return }
        isStarted = true
        do {
            dialer = dialerOf(try library.start(directory: directory, secret: secret))
        } catch let refusal as ClientError {
            failure = refusal
            ClientLog.info("the transport did not start: \(refusal.code)")
            return
        } catch {
            failure = .refusal(Transport.codeFailed, ["detail": "\(error)"])
            return
        }
        connect()
    }

    /// Stop the library: every session and every forward ends.
    func stop() {
        retry?.cancel()
        retry = nil
        control?.close()
        control = nil
        isStarted = false
        library.stop()
    }

    /// Take one hub's events from now on; a second subscription for the same hub replaces the first.
    ///
    /// - Parameters:
    ///   - binding: The hub, by the name its `dial` gives.
    ///   - handler: Called with each of its events, in order.
    func subscribe(_ binding: String, _ handler: @escaping (TransportEvent) -> Void) {
        handlers[binding] = handler
    }

    /// Stop taking one hub's events.
    ///
    /// - Parameter binding: The hub.
    func unsubscribe(_ binding: String) {
        handlers[binding] = nil
    }

    /// Send one command and call back with the transport's answer.
    ///
    /// - Parameters:
    ///   - name: The command, such as `dial` or `forward_start`.
    ///   - fields: Its fields.
    ///   - timeout: How long the answer may take, in seconds.
    ///   - completion: Called with the answer, its `{code, params}` as the refusal, `transport_missing` in a build
    ///     with no transport, or `hub_unreachable {detail}` when no answer comes in time.
    func command(
        _ name: String, _ fields: [String: JSONValue], timeout: Double = Transport.commandTimeoutSeconds,
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        if let failure {
            completion(.failure(failure))
            return
        }
        nextId += 1
        let id = "c\(nextId)"
        var line = fields
        line["id"] = .string(id)
        line["command"] = .string(name)
        answers[id] = completion
        clock.schedule(after: timeout) { [weak self] in
            guard let call = self?.answers.removeValue(forKey: id) else { return }
            call(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the transport did not answer \(name)"])))
        }
        send(line)
    }

    /// Write one frame on a hub's control stream.
    ///
    /// - Parameters:
    ///   - binding: The hub.
    ///   - frame: The frame, with its `type`.
    /// - Returns: False while the transport has no control connection.
    @discardableResult
    func frame(_ binding: String, _ frame: [String: JSONValue]) -> Bool {
        guard let control, !control.isClosed else { return false }
        let line: [String: JSONValue] = ["frame": .object(frame), "binding": .string(binding)]
        return control.write(Data(line.jsonText.utf8) + Data([0x0A]))
    }

    /// Open one stream on a hub's session, on a local connection of its own.
    ///
    /// - Parameters:
    ///   - binding: The hub.
    ///   - open: The stream's `open` record, `{kind, ...args}`.
    ///   - carriage: What it carries after its `accept`.
    /// - Returns: The stream, or the refusal: `transport_missing`, or `hub_unreachable`.
    func open(_ binding: String, open: [String: JSONValue], carriage: TransportStream.Carriage) -> Result<
        TransportStream, ClientError
    > {
        if let failure { return .failure(failure) }
        guard let dialer else {
            return .failure(.refusal(Channel.codeHubUnreachable, ["detail": "the transport has not started"]))
        }
        do {
            return .success(
                try TransportStream.open(
                    dialer: dialer, secret: secret, binding: binding, open: open, carriage: carriage))
        } catch let refusal as ClientError {
            return .failure(refusal)
        } catch {
            return .failure(.refusal(Channel.codeHubUnreachable, ["detail": "\(error)"]))
        }
    }

    private func connect() {
        guard isStarted, let dialer else { return }
        let link: TransportLink
        do {
            link = TransportLink(descriptor: try dialer.dial())
        } catch {
            ClientLog.info("the transport's local channel did not open: \(error)")
            retryLater()
            return
        }
        control = link
        buffer = Data()
        link.onData = { [weak self] data in self?.take(data) }
        link.onEnd = { [weak self] in self?.controlEnded() }
        link.start()
        let first: [String: JSONValue] = ["secret": .string(secret), "op": .string("control")]
        link.write(Data(first.jsonText.utf8) + Data([0x0A]))
        let queued = waiting
        waiting = []
        for line in queued { link.write(line) }
        if hasOpened {
            for handler in Array(handlers.values) { handler(.restarted) }
        }
        hasOpened = true
    }

    private func retryLater() {
        retry = clock.schedule(after: Transport.reconnectSeconds) { [weak self] in
            self?.retry = nil
            self?.connect()
        }
    }

    private func controlEnded() {
        control = nil
        let pending = answers
        answers = [:]
        for (_, call) in pending {
            call(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the transport's local channel dropped"])))
        }
        ClientLog.info("the transport's local channel dropped; it opens again")
        retryLater()
    }

    private func send(_ line: [String: JSONValue]) {
        let bytes = Data(line.jsonText.utf8) + Data([0x0A])
        if let control, !control.isClosed {
            control.write(bytes)
        } else {
            waiting.append(bytes)
        }
    }

    private func take(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<end]
            buffer = Data(buffer[(end + 1)...])
            guard let parsed = (try? JSONValue.parse(Data(line)))?.objectValue else { continue }
            dispatch(parsed)
        }
    }

    private func dispatch(_ line: [String: JSONValue]) {
        let binding = line.text("binding")
        if let frame = line["frame"]?.objectValue {
            handlers[binding]?(.frame(frame))
            return
        }
        switch line.text("event") {
        case "session_open":
            handlers[binding]?(
                .sessionOpen(
                    address: line.text("address"), path: line.text("path"),
                    handshakeMs: line["handshake_ms"]?.intValue ?? 0))
        case "round_end":
            let next = line["next_round_s"].map { Double($0.text) ?? 0 } ?? 0
            handlers[binding]?(.roundEnd(refusal(line), nextRoundSeconds: next))
        case "session_end":
            handlers[binding]?(.sessionEnd(refusal(line)))
        case "forward_end":
            let protocolName = line.text("protocol")
            onForwardEnd?(
                TransportForwardEnd(
                    listen: line.text("listen"), protocol: protocolName.isEmpty ? "tcp" : protocolName,
                    refusal: refusal(line)))
        case "":
            guard line["question"] == nil, let call = answers.removeValue(forKey: line.text("id")) else { return }
            if let refused = refusal(line) {
                call(.failure(refused))
            } else {
                call(.success(line))
            }
        default:
            break
        }
    }

    private func refusal(_ line: [String: JSONValue]) -> ClientError? {
        let code = line.text("code")
        return code.isEmpty ? nil : .refused(code: code, params: line.object("params"))
    }

    /// A fresh secret for the local channel.
    ///
    /// - Returns: 32 random bytes in lowercase hex.
    static func freshSecret() -> String {
        var generator = SystemRandomNumberGenerator()
        return (0..<Transport.secretBytes).map { _ in
            String(format: "%02x", UInt8.random(in: 0...255, using: &generator))
        }
        .joined()
    }
}
