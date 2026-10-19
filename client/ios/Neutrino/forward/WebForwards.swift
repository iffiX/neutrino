import Foundation

/// The loopback forwards of the app core, by entry key `<binding>/<entry>`. Each forward listens on `127.0.0.1`
/// at the number the local port table gives its entry, and every connection it accepts is one `connect` stream
/// to the hub naming the entry. A web entry forwards from Open until Disconnect, its Open reading the entry's
/// token on the `service` stream when it needs one and opening the in-app browser on the loopback; the hub's
/// panel, keyed `<binding>/#panel`, forwards from the first press of Panel until the hub is left, each press
/// reading a one-time sign-in token first. A forward stops when its hub is left and when its entry leaves the
/// hub's state. While its hub has no channel, a forward accepts nothing and stays bound. Every call runs on the
/// main queue.
final class WebForwards {
    private let table: LocalPortTable
    private let openConnect: (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>
    private let material:
        (String, [String: JSONValue], @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void
    private var relays: [String: ForwardRelay] = [:]
    private var targets: [String: ForwardTarget] = [:]
    private var channelless: Set<String> = []
    private var suspended: [String: Int] = [:]

    /// Called after every change of a row.
    var onChange: (() -> Void)?

    /// Every row with a forward, a job or an error, by entry key.
    private(set) var rows: [String: ForwardRow] = [:] {
        didSet {
            if rows != oldValue { onChange?() }
        }
    }

    /// Prepare the forwards.
    ///
    /// - Parameters:
    ///   - table: The local port of every forwarded entry.
    ///   - openConnect: Opens one `connect` stream on a hub, by binding id and the stream's arguments.
    ///   - material: Reads what the hub hands this phone on a `service` stream, by binding id and arguments.
    init(
        table: LocalPortTable,
        openConnect: @escaping (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>,
        material:
            @escaping (String, [String: JSONValue], @escaping (Result<[String: JSONValue], ClientError>) -> Void)
            -> Void
    ) {
        self.table = table
        self.openConnect = openConnect
        self.material = material
    }

    /// Press Open on a web entry: its forward is made when it has none, a fresh token is read on the `service`
    /// stream when the entry needs one, and the in-app browser opens `<scheme>://127.0.0.1:<local port><path>`,
    /// with `?tkn=<token>` for a token entry. A press while the row's job runs is dropped.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    ///   - url: The entry's address, where it stands on the hub's networks.
    ///   - isTokenRequired: Whether the page opens with a token.
    ///   - onOpen: What opening the loopback address in the in-app browser does.
    func open(
        bindingId: String, entryId: String, url: String, isTokenRequired: Bool, onOpen: @escaping (String) -> Void
    ) {
        let key = Self.key(bindingId, entryId)
        guard begin(key, .opening) else { return }
        guard let target = ForwardWebTarget(url) else {
            rows[key] = ForwardRow(localPort: rows[key]?.localPort ?? 0, error: .refusal("unknown_request"))
            return
        }
        let args: [String: JSONValue] = ["id": .string(entryId)]
        let bound: Int
        switch forward(key, bindingId: bindingId, args: args, port: target.port) {
        case .failure(let refusal):
            rows[key] = ForwardRow(error: refusal)
            return
        case .success(let port):
            bound = port
        }
        let address = "\(target.scheme)://\(Forward.bindHost):\(bound)\(target.path)"
        guard isTokenRequired else {
            onOpen(address)
            rows[key] = ForwardRow(localPort: bound)
            return
        }
        material(bindingId, args) { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let refusal):
                self.rows[key] = ForwardRow(localPort: self.relays[key]?.localPort ?? 0, error: refusal)
            case .success(let answer):
                let token = answer.text("token")
                guard !token.isEmpty else {
                    self.rows[key] = ForwardRow(localPort: bound, error: .refusal("web_token_missing"))
                    return
                }
                onOpen(Self.tokenUrl(address, token: token))
                self.rows[key] = ForwardRow(localPort: self.relays[key]?.localPort ?? 0)
            }
        }
    }

    /// Press Panel on a hub's row: a one-time `{token}` is read on a `service` stream with `{is_panel: true}`,
    /// the panel's forward is made when the hub has none, and the in-app browser opens
    /// `http://127.0.0.1:<local port>/?tkn=<token>`. A refusal of either is the row's error and opens nothing.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - onOpen: What opening the loopback address in the in-app browser does.
    func openPanel(bindingId: String, onOpen: @escaping (String) -> Void) {
        let key = Self.panelKey(bindingId)
        guard begin(key, .opening) else { return }
        let args: [String: JSONValue] = ["is_panel": .bool(true)]
        material(bindingId, args) { [weak self] result in
            guard let self else { return }
            let held = self.relays[key]?.localPort ?? 0
            switch result {
            case .failure(let refusal):
                self.rows[key] = ForwardRow(localPort: held, error: refusal)
            case .success(let answer):
                let token = answer.text("token")
                guard !token.isEmpty else {
                    self.rows[key] = ForwardRow(localPort: held, error: .refusal("web_token_missing"))
                    return
                }
                switch self.forward(key, bindingId: bindingId, args: args, port: 0) {
                case .failure(let refusal):
                    self.rows[key] = ForwardRow(error: refusal)
                case .success(let bound):
                    onOpen(Self.tokenUrl("http://\(Forward.bindHost):\(bound)/", token: token))
                    self.rows[key] = ForwardRow(localPort: bound)
                }
            }
        }
    }

    /// Press Disconnect on a forwarded entry. A press while the row's job runs is dropped.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    func disconnect(bindingId: String, entryId: String) {
        let key = Self.key(bindingId, entryId)
        guard begin(key, .disconnecting) else { return }
        stop(key, why: "the person disconnected")
        rows[key] = nil
    }

    /// One entry's local port, as the Configure dialog opens on it.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    /// - Returns: Automatic or fixed, with the number held.
    func choice(bindingId: String, entryId: String) -> LocalPortChoice {
        table.choice(of: Self.key(bindingId, entryId))
    }

    /// Save the Configure dialog: one entry's local port, while the entry is not forwarded.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    ///   - choice: Automatic, or fixed with a number from 1024 to 65535.
    /// - Throws: `ClientError.refused` with `disconnect_first` while the entry is forwarded, `port_range` for a
    ///   number outside 1024 to 65535, and `port_taken {port}` when another entry holds it.
    func configure(bindingId: String, entryId: String, choice: LocalPortChoice) throws {
        let key = Self.key(bindingId, entryId)
        if relays[key]?.isActive == true { throw ClientError.refusal("disconnect_first") }
        try table.configure(key, choice)
    }

    /// Take one round of the hubs' state: a forward stops when its hub is gone, or when its hub serves this phone
    /// and no longer lists its entry; the panel's when its hub no longer lets this phone open the panel. A forward
    /// whose hub has no channel accepts nothing until it is back.
    ///
    /// - Parameter hubs: Every hub's view.
    func take(_ hubs: [HubView]) {
        let byId = Dictionary(hubs.map { ($0.binding.id, $0) }, uniquingKeysWith: { first, _ in first })
        channelless = Set(hubs.filter { $0.connectedAddress.isEmpty }.map(\.binding.id))
        var gone: [(String, String)] = []
        for (key, relay) in relays {
            let bindingId = Self.bindingId(of: key)
            relay.channelChanged(isOpen: !channelless.contains(bindingId))
            guard let hub = byId[bindingId] else {
                gone.append((key, "the hub was left"))
                continue
            }
            guard hub.isConnected else { continue }
            let entryId = String(key.dropFirst(bindingId.count + 1))
            if entryId == Forward.panelEntry {
                if !hub.isPanelAllowed { gone.append((key, "the hub took the panel away")) }
            } else if !hub.services.contains(where: { $0.id == entryId }) {
                gone.append((key, "the hub withdrew the entry"))
            }
        }
        for (key, why) in gone { stop(key, why: why) }
    }

    /// A hub is being left: its forwards stop and its rows go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        for key in relays.keys where key.hasPrefix("\(bindingId)/") { stop(key, why: "the hub was left") }
        rows = rows.filter { !$0.key.hasPrefix("\(bindingId)/") }
        suspended = suspended.filter { !$0.key.hasPrefix("\(bindingId)/") }
        table.forget(bindingId: bindingId)
    }

    /// The app is about to be suspended: every listener stops, each one's number kept for `foreground()`.
    func suspend() {
        for (key, relay) in relays {
            suspended[key] = relay.localPort
            relay.close()
        }
        relays = [:]
    }

    /// The app came back to the foreground: every forward that listened before listens again on its number.
    func foreground() {
        let waiting = suspended
        suspended = [:]
        for (key, port) in waiting {
            guard let target = targets[key] else { continue }
            if case .failure(let refusal) = forward(key, bindingId: target.bindingId, args: target.args, port: port) {
                rows[key] = ForwardRow(error: refusal)
            }
        }
    }

    /// A refresh: every row's error goes.
    func clearErrors() {
        var next: [String: ForwardRow] = [:]
        for (key, row) in rows {
            var kept = row
            kept.error = nil
            if kept != ForwardRow() { next[key] = kept }
        }
        rows = next
    }

    private func begin(_ key: String, _ job: ForwardJob) -> Bool {
        var row = rows[key] ?? ForwardRow()
        guard row.job == nil else {
            ClientLog.info("a forward job runs on \(key); the press is dropped")
            return false
        }
        row.job = job
        row.error = nil
        rows[key] = row
        return true
    }

    private func forward(_ key: String, bindingId: String, args: [String: JSONValue], port: Int) -> Result<
        Int, ClientError
    > {
        if let relay = relays[key], relay.isActive { return .success(relay.localPort) }
        do {
            let local = try table.port(for: key, publishedPort: port)
            let relay = ForwardRelay(name: key) { [weak self] in
                self?.openConnect(bindingId, args)
                    ?? .failure(.refusal(Channel.codeHubUnreachable, ["detail": "the app core stopped"]))
            }
            relay.channelChanged(isOpen: !channelless.contains(bindingId))
            try relay.start(port: local)
            relays[key]?.close()
            relays[key] = relay
            targets[key] = ForwardTarget(bindingId: bindingId, args: args)
            ClientLog.info("forwarding \(Forward.bindHost):\(relay.localPort) to \(key) through the hub")
            return .success(relay.localPort)
        } catch let refusal as ClientError {
            return .failure(refusal)
        } catch {
            return .failure(.refusal("forward_failed", ["detail": "\(error)"]))
        }
    }

    private func stop(_ key: String, why: String) {
        guard let relay = relays.removeValue(forKey: key) else { return }
        relay.close()
        targets[key] = nil
        ClientLog.info("stopped forwarding \(Forward.bindHost):\(relay.localPort) to \(key): \(why)")
        guard var row = rows[key] else { return }
        row.localPort = 0
        rows[key] = row == ForwardRow() ? nil : row
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

    /// The key of a hub's panel forward.
    ///
    /// - Parameter bindingId: The hub.
    /// - Returns: `<binding>/#panel`.
    static func panelKey(_ bindingId: String) -> String {
        key(bindingId, Forward.panelEntry)
    }

    /// An address with the token it opens with.
    ///
    /// - Parameters:
    ///   - url: The address.
    ///   - token: The token the hub handed for this open.
    /// - Returns: The address with `tkn=<token>` added to its query.
    static func tokenUrl(_ url: String, token: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?#")
        let encoded = token.addingPercentEncoding(withAllowedCharacters: allowed) ?? token
        return url + (url.contains("?") ? "&" : "?") + "\(Forward.tokenParameter)=\(encoded)"
    }

    private static func bindingId(of key: String) -> String {
        String(key.prefix { $0 != "/" })
    }
}
