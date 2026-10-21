import Foundation

/// The remote desktop jobs of the app core: a Connect reading an entry's seat password and making its forward, the
/// one viewer open, which dials that forward on the loopback, and the code a failed Connect ended in, each by entry
/// key `<binding>/<entry>`. The forward is the viewer's own, as the share page's is: it listens on `127.0.0.1` at a
/// port the system picks, each accepted connection one `connect` stream naming the entry, accepts nothing while the
/// hub has no channel, stops when the hub no longer lists the entry, and ends with the viewer. Every call runs on
/// the main queue.
final class RemoteDesktopSessions {
    private let material: (String, String, @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void
    private let openConnect: (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>
    private let choiceOf: (String) -> RemoteDesktopChoice
    private var relay: ForwardRelay?
    private var channelless: Set<String> = []

    /// Called after every change of `connecting`, `errors` or `viewing`.
    var onChange: (() -> Void)?

    /// The entries whose Connect runs.
    private(set) var connecting: Set<String> = [] {
        didSet {
            if connecting != oldValue { onChange?() }
        }
    }

    /// The code each entry's last Connect ended in, until its next press or a refresh.
    private(set) var errors: [String: ClientError] = [:] {
        didSet {
            if errors != oldValue { onChange?() }
        }
    }

    /// The target of the viewer open, or nil.
    private(set) var viewing: RemoteDesktopTarget? {
        didSet {
            if viewing != oldValue { onChange?() }
        }
    }

    /// Prepare the jobs.
    ///
    /// - Parameters:
    ///   - material: Reads what the hub hands this phone for one entry, by binding id and entry id.
    ///   - openConnect: Opens one `connect` stream on a hub, by binding id and the stream's arguments.
    ///   - choiceOf: The codec and quality kept for an entry, by entry key.
    init(
        material: @escaping (String, String, @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void,
        openConnect: @escaping (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>,
        choiceOf: @escaping (String) -> RemoteDesktopChoice
    ) {
        self.material = material
        self.openConnect = openConnect
        self.choiceOf = choiceOf
    }

    /// Press Connect on an entry: its seat password is read, its forward is made, and the viewer opens on the
    /// forward with the entry's kept codec and quality. A press while that entry's Connect runs or a viewer is open
    /// is dropped.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    ///   - name: What the viewer names.
    ///   - platformOs: The `platform_os` the entry carries, or empty when it names none.
    func connect(bindingId: String, entryId: String, name: String, platformOs: String) {
        let key = Self.key(bindingId, entryId)
        if connecting.contains(key) || viewing != nil {
            ClientLog.info("a viewer runs or opens; the connect of \(key) is dropped")
            return
        }
        connecting.insert(key)
        errors[key] = nil
        material(bindingId, entryId) { [weak self] answer in
            guard let self else { return }
            let bound = answer.flatMap { _ in self.forward(bindingId: bindingId, entryId: entryId) }
            switch bound.flatMap({ RemoteDesktopTarget.of(key: key, name: name, answer: answer, localPort: $0) }) {
            case .failure(let refusal):
                self.errors[key] = refusal
            case .success(var target):
                target.choice = self.choiceOf(key)
                target.platformOs = platformOs
                self.viewing = target
            }
            self.connecting.remove(key)
        }
    }

    /// Close the viewer; its forward ends.
    func close() {
        stopForward(why: "its viewer closed")
        viewing = nil
    }

    /// Take one round of the hubs' state: the forward of a hub without a channel accepts nothing, and stops when
    /// its hub serves this phone without its entry.
    ///
    /// - Parameter hubs: Every hub's view.
    func take(_ hubs: [HubView]) {
        channelless = Set(hubs.filter { $0.connectedAddress.isEmpty }.map(\.binding.id))
        guard let viewed = viewing, relay != nil else { return }
        let bindingId = Self.bindingId(of: viewed.key)
        relay?.channelChanged(isOpen: !channelless.contains(bindingId))
        guard let hub = hubs.first(where: { $0.binding.id == bindingId }), hub.isConnected else { return }
        let entryId = String(viewed.key.dropFirst(bindingId.count + 1))
        if !hub.services.contains(where: { $0.id == entryId }) { stopForward(why: "the hub withdrew the entry") }
    }

    /// A hub is being left: its viewer closes and its errors go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        if viewing?.key.hasPrefix("\(bindingId)/") == true { close() }
        errors = errors.filter { !$0.key.hasPrefix("\(bindingId)/") }
    }

    /// A refresh: every entry's error goes.
    func clearErrors() {
        errors = [:]
    }

    /// The key of one entry.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    /// - Returns: `<binding>/<entry>`.
    static func key(_ bindingId: String, _ entryId: String) -> String {
        "\(bindingId)/\(entryId)"
    }

    private func forward(bindingId: String, entryId: String) -> Result<Int, ClientError> {
        stopForward(why: "a new viewer opens")
        let key = Self.key(bindingId, entryId)
        let relay = ForwardRelay(name: key) { [weak self] in
            self?.openConnect(bindingId, ["id": .string(entryId)])
                ?? .failure(.refusal(Channel.codeHubUnreachable, ["detail": "the viewer closed"]))
        }
        relay.channelChanged(isOpen: !channelless.contains(bindingId))
        do {
            let port = try relay.start(port: 0)
            self.relay = relay
            ClientLog.info("forwarding \(Forward.bindHost):\(port) to the desktop \(key) through the hub")
            return .success(port)
        } catch let refusal as ClientError {
            return .failure(refusal)
        } catch {
            return .failure(.refusal("forward_failed", ["detail": "\(error)"]))
        }
    }

    private func stopForward(why: String) {
        guard let relay else { return }
        self.relay = nil
        relay.close()
        ClientLog.info("stopped forwarding \(Forward.bindHost):\(relay.localPort) to \(relay.name): \(why)")
    }

    private static func bindingId(of key: String) -> String {
        String(key.prefix { $0 != "/" })
    }
}
