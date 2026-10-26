import Foundation

@testable import Neutrino

#if canImport(Darwin)
    import Darwin
#else
    import Glibc
#endif

/// A transport faked at its local channel: it takes the library's start, serves the control connection's lines
/// and every stream connection over a socket pair, answers each command by `answer`, and records what the app
/// wrote. Every call runs on the main queue.
final class FakeTransport: TransportLibrary, TransportDialer {
    /// Whether it plays a build with no transport library.
    var isMissing = false

    /// The secret the library was started with.
    private(set) var secret = ""

    /// Every command the app sent, in order.
    private(set) var commands: [[String: JSONValue]] = []

    /// Every frame line the app wrote: the binding and the frame.
    private(set) var frames: [(binding: String, frame: [String: JSONValue])] = []

    /// Every stream the app opened, by its `open` record, with the transport's end.
    private(set) var streams: [(open: [String: JSONValue], end: FakeTransportEnd)] = []

    /// The answer to each command, as the transport writes it, without its `id`; nil answers nothing.
    var answer: ([String: JSONValue]) -> [String: JSONValue]? = { _ in [:] }

    /// How a stream the app opens is served, with its `open` record and the transport's end.
    var serve: ([String: JSONValue], FakeTransportEnd) -> Void = { _, end in end.accept() }

    private var control: FakeTransportEnd?
    private var ends: [FakeTransportEnd] = []

    func start(directory: String, secret: String) throws -> String {
        if isMissing { throw ClientError.refusal(Transport.codeMissing) }
        self.secret = secret
        return directory + "/transport.sock"
    }

    func stop() {}

    func dial() throws -> Int32 {
        var pair: [Int32] = [0, 0]
        guard socketpair(AF_UNIX, ForwardSocket.streamType, 0, &pair) == 0 else {
            throw ClientError.refusal(Channel.codeHubUnreachable, ["detail": "socketpair"])
        }
        ForwardSocket.prepare(pair[0])
        ForwardSocket.prepare(pair[1])
        let end = FakeTransportEnd(descriptor: pair[1])
        ends.append(end)
        end.onLine = { [weak self, weak end] line in
            guard let self, let end else { return }
            self.first(line, on: end)
        }
        end.start()
        return pair[0]
    }

    /// Send one event about a hub.
    ///
    /// - Parameters:
    ///   - name: The event.
    ///   - binding: The hub.
    ///   - fields: Its other fields.
    func event(_ name: String, _ binding: String, _ fields: [String: JSONValue] = [:]) {
        var line = fields
        line["event"] = .string(name)
        line["binding"] = .string(binding)
        control?.writeLine(line)
    }

    /// Send one frame from the hub.
    ///
    /// - Parameters:
    ///   - binding: The hub.
    ///   - frame: The frame.
    func frame(_ binding: String, _ frame: [String: JSONValue]) {
        control?.writeLine(["frame": .object(frame), "binding": .string(binding)])
    }

    /// Send any line on the control connection.
    ///
    /// - Parameter line: The line.
    func send(_ line: [String: JSONValue]) {
        control?.writeLine(line)
    }

    /// Drop the control connection, as a transport that ended would.
    func dropControl() {
        control?.close()
        control = nil
    }

    /// The commands of one name the app sent.
    ///
    /// - Parameter name: The command.
    /// - Returns: Their lines, in order.
    func sent(_ name: String) -> [[String: JSONValue]] {
        commands.filter { $0.text("command") == name }
    }

    /// The frames of one type the app wrote.
    ///
    /// - Parameter type: The frame's `type`.
    /// - Returns: The frames, in order.
    func written(_ type: String) -> [[String: JSONValue]] {
        frames.map(\.frame).filter { $0.text("type") == type }
    }

    private func first(_ line: [String: JSONValue], on end: FakeTransportEnd) {
        guard line.text("secret") == secret else {
            end.close()
            return
        }
        switch line.text("op") {
        case "control":
            control = end
            end.onLine = { [weak self, weak end] next in
                guard let self, let end else { return }
                self.take(next, on: end)
            }
        case "open":
            let open = line.object("open")
            end.isRaw = true
            streams.append((open, end))
            serve(open, end)
        default:
            end.close()
        }
    }

    private func take(_ line: [String: JSONValue], on end: FakeTransportEnd) {
        if let frame = line["frame"]?.objectValue {
            frames.append((line.text("binding"), frame))
            return
        }
        commands.append(line)
        guard var reply = answer(line) else { return }
        reply["id"] = line["id"]
        end.writeLine(reply)
    }
}
