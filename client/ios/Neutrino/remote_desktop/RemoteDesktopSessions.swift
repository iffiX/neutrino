import Foundation

/// The remote desktop jobs of the app core: a Connect reading an entry's seat password and making its forward, the
/// one viewer open, which dials that forward on the loopback, and the code a failed Connect ended in, each by entry
/// key `<binding>/<entry>`. The forward ends with the viewer. Every call runs on the main queue.
final class RemoteDesktopSessions {
    private let material: (String, String, @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void
    private let forward: (String, String, Int) -> Result<Int, ClientError>
    private let release: (String, String) -> Void
    private let choiceOf: (String) -> RemoteDesktopChoice

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
    ///   - forward: Makes an entry's forward, by binding id, entry id and the entry's own port; the loopback number.
    ///   - release: Ends an entry's forward, by binding id and entry id.
    ///   - choiceOf: The codec and quality kept for an entry, by entry key.
    init(
        material: @escaping (String, String, @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void,
        forward: @escaping (String, String, Int) -> Result<Int, ClientError>,
        release: @escaping (String, String) -> Void,
        choiceOf: @escaping (String) -> RemoteDesktopChoice
    ) {
        self.material = material
        self.forward = forward
        self.release = release
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
    ///   - port: The entry's own port, which its forward tries first on the loopback.
    func connect(bindingId: String, entryId: String, name: String, platformOs: String, port: Int) {
        let key = Self.key(bindingId, entryId)
        if connecting.contains(key) || viewing != nil {
            ClientLog.info("a viewer runs or opens; the connect of \(key) is dropped")
            return
        }
        connecting.insert(key)
        errors[key] = nil
        material(bindingId, entryId) { [weak self] answer in
            guard let self else { return }
            let bound: Result<Int, ClientError>
            switch answer {
            case .success: bound = self.forward(bindingId, entryId, port)
            case .failure(let refusal): bound = .failure(refusal)
            }
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
        guard let viewed = viewing else { return }
        viewing = nil
        let bindingId = String(viewed.key.prefix { $0 != "/" })
        release(bindingId, String(viewed.key.dropFirst(bindingId.count + 1)))
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
}
