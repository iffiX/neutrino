import Foundation

/// The loopback forwards of the app core, held by the transport. An app's Use forwards each of its `web` and
/// `port` entries at its local port, the person's number or the hub's, and the app is in use until Stop, its hub's
/// leave or the app's quit; Open opens the in-app browser at `127.0.0.1` on the app's first `http` or `https`
/// entry, with a fresh token for an entry that takes one. The hub's panel's forward lives from the first press of
/// Panel until the hub is left, on a number picked from 20000 to 23999 and kept. A forward stops when its hub is
/// left and when its entry leaves the hub's state; every listener stops when the app is suspended and listens
/// again on its number when the app comes back. Every call runs on the main queue.
final class AppForwards {
    private let table: LocalPortTable
    private let forwarder: LocalForwarder
    private let clock: ClientClock
    private let material:
        (String, [String: JSONValue], @escaping (Result<[String: JSONValue], ClientError>) -> Void) -> Void
    private var listening: [String: ForwardListener] = [:]
    private var suspended: [String: ForwardListener] = [:]

    /// Called after every change of a row.
    var onChange: (() -> Void)?

    /// Every app's and panel's row with a forward, a job or an error, by key `<binding>/<app>`.
    private(set) var rows: [String: ForwardRow] = [:] {
        didSet {
            if rows != oldValue { onChange?() }
        }
    }

    /// Prepare the forwards.
    ///
    /// - Parameters:
    ///   - table: The local port of every forwarded entry.
    ///   - forwarder: Holds the listeners.
    ///   - clock: The timer that starts a UDP forward again.
    ///   - material: Reads what the hub hands this phone on a `service` frame, by binding id and arguments.
    init(
        table: LocalPortTable, forwarder: LocalForwarder, clock: ClientClock,
        material:
            @escaping (String, [String: JSONValue], @escaping (Result<[String: JSONValue], ClientError>) -> Void)
            -> Void
    ) {
        self.table = table
        self.forwarder = forwarder
        self.clock = clock
        self.material = material
    }

    /// Press Use on an app: every entry's forward it has not got, in the hub's order, but an entry with no number,
    /// the hub having sent none and the person set none; the app is in use once one listens. A failure writes its code on the row, and the forwards that started stay up. A press while the row's
    /// job runs is dropped.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - app: The app.
    func use(hub: HubView, app: ChannelApp) {
        let bindingId = hub.binding.id
        let key = Self.key(bindingId, app.id)
        guard begin(key, .opening) else { return }
        let entries = Self.entries(of: hub, app: app).filter { port(bindingId: bindingId, entry: $0) > 0 }
        forwardEach(bindingId, entries[...], failure: nil) { [weak self] failure in
            guard let self else { return }
            let isAny = entries.contains { self.listening[Self.key(bindingId, $0.id)] != nil }
            var row = self.rows[key] ?? ForwardRow()
            row.isInUse = row.isInUse || isAny
            row.job = nil
            row.error = failure
            self.rows[key] = row
        }
    }

    /// Press Open on an app in use: the in-app browser at `127.0.0.1` on its first `http` or `https` entry, whose
    /// forward listens again if it does not, with a fresh token where that entry takes one. A press while the app
    /// is not in use, has no such entry or runs a job is dropped.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - app: The app.
    ///   - onOpen: What opening the loopback address in the in-app browser does.
    func open(hub: HubView, app: ChannelApp, onOpen: @escaping (String) -> Void) {
        let bindingId = hub.binding.id
        let key = Self.key(bindingId, app.id)
        guard rows[key]?.isInUse == true, let page = Self.page(of: hub, app: app), begin(key, .opening) else { return }
        let settle: (ClientError?) -> Void = { [weak self] error in
            guard let self else { return }
            var row = self.rows[key] ?? ForwardRow()
            row.job = nil
            row.error = error
            self.rows[key] = row
        }
        forward(bindingId, entry: page) { [weak self] result in
            guard let self else { return }
            if case .failure(let refusal) = result {
                settle(refusal)
                return
            }
            self.open(bindingId: bindingId, entry: page, onOpen: onOpen, completion: settle)
        }
    }

    /// Press Stop on an app: every forward of the app ends. A press while the row's job runs is dropped.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - appId: The app.
    func stop(bindingId: String, appId: String) {
        let key = Self.key(bindingId, appId)
        guard begin(key, .disconnecting) else { return }
        for (entryKey, listener) in listening where listener.appKey == key {
            end(entryKey, why: "the person stopped the app")
        }
        var row = rows[key] ?? ForwardRow()
        row.isInUse = false
        row.job = nil
        rows[key] = row == ForwardRow() ? nil : row
    }

    /// The numbers the person set for an app's entries, as its Configure dialog opens on them.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entries: The app's entries.
    /// - Returns: Each entry's number by entry id, nil where it takes the hub's.
    func numbers(bindingId: String, entries: [ChannelServiceEntry]) -> [String: Int?] {
        Dictionary(uniqueKeysWithValues: entries.map { ($0.id, table.number(of: Self.key(bindingId, $0.id))) })
    }

    /// The number an app entry listens on: the person's, else the hub's.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entry: The entry.
    /// - Returns: The number.
    func port(bindingId: String, entry: ChannelServiceEntry) -> Int {
        table.port(of: Self.key(bindingId, entry.id), hubPort: entry.localPort)
    }

    /// Save an app's Configure dialog, while the app is not in use.
    ///
    /// - Parameters:
    ///   - hubs: Every hub, for the hub numbers a number may not take.
    ///   - bindingId: The hub.
    ///   - appId: The app.
    ///   - numbers: Each entry's number by entry id, nil to go back to the hub's.
    /// - Throws: `ClientError.refused` with `disconnect_first` while the app is in use, `port_range` for a number
    ///   outside 1024 to 65535, and `port_taken {port}` when another entry of the protocol holds it.
    func configure(hubs: [HubView], bindingId: String, appId: String, numbers: [String: Int?]) throws {
        if rows[Self.key(bindingId, appId)]?.isInUse == true { throw ClientError.refusal("disconnect_first") }
        var hubNumbers: [String: (port: Int, protocol: String)] = [:]
        for hub in hubs {
            for entry in hub.services where entry.localPort > 0 {
                hubNumbers[Self.key(hub.binding.id, entry.id)] = (entry.localPort, entry.protocol)
            }
        }
        guard let hub = hubs.first(where: { $0.binding.id == bindingId }) else { return }
        for (entryId, number) in numbers {
            guard let entry = hub.services.first(where: { $0.id == entryId && $0.appId == appId }) else { continue }
            try table.configure(
                Self.key(bindingId, entryId), number: number, protocol: entry.protocol, hubNumbers: hubNumbers)
        }
    }

    /// Press Panel on a hub's row: a one-time `{token}` is read on a `service` frame with `{is_panel: true}`, the
    /// panel's forward is made when the hub has none, and the in-app browser opens
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
            let settle: (Int?, ClientError?) -> Void = { port, error in
                var row = self.rows[key] ?? ForwardRow()
                if let port { row.localPort = port }
                row.job = nil
                row.error = error
                self.rows[key] = row == ForwardRow() ? nil : row
            }
            switch result {
            case .failure(let refusal):
                settle(nil, refusal)
            case .success(let answer):
                let token = answer.text("token")
                guard !token.isEmpty else {
                    settle(nil, .refusal("web_token_missing"))
                    return
                }
                let open: [String: JSONValue] = ["kind": .string(Channel.kindConnect), "is_panel": .bool(true)]
                self.pick(bindingId, entryKey: key, rowKey: key, open: open) { result in
                    switch result {
                    case .failure(let refusal):
                        settle(nil, refusal)
                    case .success(let port):
                        onOpen(Self.tokenUrl("http://\(Forward.bindHost):\(port)/", token: token))
                        settle(port, nil)
                    }
                }
            }
        }
    }

    /// Take one round of the hubs' state: a forward stops when its hub is gone, or when its hub serves this phone
    /// and no longer lists its entry; the panel's when its hub no longer lets this phone open the panel.
    ///
    /// - Parameter hubs: Every hub's view.
    func take(_ hubs: [HubView]) {
        let byId = Dictionary(hubs.map { ($0.binding.id, $0) }, uniquingKeysWith: { first, _ in first })
        for (entryKey, listener) in listening {
            guard let hub = byId[listener.bindingId] else {
                end(entryKey, why: "the hub was left")
                continue
            }
            guard hub.isConnected else { continue }
            let entryId = String(entryKey.dropFirst(listener.bindingId.count + 1))
            if entryId == Forward.panelEntry {
                if !hub.isPanelAllowed { end(entryKey, why: "the hub took the panel away") }
            } else if !hub.services.contains(where: { $0.id == entryId }) {
                end(entryKey, why: "the hub withdrew the entry")
            }
        }
    }

    /// A hub is being left: its forwards stop and its rows go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        for key in listening.keys where key.hasPrefix("\(bindingId)/") { end(key, why: "the hub was left") }
        rows = rows.filter { !$0.key.hasPrefix("\(bindingId)/") }
        suspended = suspended.filter { !$0.key.hasPrefix("\(bindingId)/") }
        table.forget(bindingId: bindingId)
    }

    /// The app is about to be suspended: every listener stops, each one kept for `foreground()`.
    func suspend() {
        for (key, listener) in listening {
            suspended[key] = listener
            forwarder.stop(port: listener.port, protocol: listener.protocol)
        }
        listening = [:]
    }

    /// The app came back to the foreground: every forward that listened before listens again on its number.
    func foreground() {
        let waiting = suspended
        suspended = [:]
        for (key, listener) in waiting {
            listen(
                listener.bindingId, entryKey: key, appKey: listener.appKey, port: listener.port,
                protocol: listener.protocol, open: listener.open
            ) { [weak self] result in
                if case .failure(let refusal) = result {
                    self?.rows[listener.appKey, default: ForwardRow()].error = refusal
                }
            }
        }
    }

    /// The transport ended a listener: a UDP forward whose stream the hub closed with a code writes the code on its
    /// app's row and listens again a second later while its app is in use.
    ///
    /// - Parameter ended: The listener and its code.
    func ended(_ ended: TransportForwardEnd) {
        guard let port = ended.listen.split(separator: ":").last.flatMap({ Int($0) }),
            let (key, listener) = listening.first(where: {
                $0.value.port == port && $0.value.protocol == ended.protocol
            })
        else { return }
        listening[key] = nil
        if let refusal = ended.refusal { rows[listener.appKey, default: ForwardRow()].error = refusal }
        guard listener.protocol == Forward.protocolUdp else { return }
        clock.schedule(after: Forward.udpRestartSeconds) { [weak self] in
            guard let self, self.rows[listener.appKey]?.isInUse == true, self.listening[key] == nil else { return }
            self.listen(
                listener.bindingId, entryKey: key, appKey: listener.appKey, port: listener.port,
                protocol: listener.protocol, open: listener.open
            ) { [weak self] result in
                if case .failure(let refusal) = result {
                    self?.rows[listener.appKey, default: ForwardRow()].error = refusal
                }
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

    private func forwardEach(
        _ bindingId: String, _ entries: ArraySlice<ChannelServiceEntry>, failure: ClientError?,
        completion: @escaping (ClientError?) -> Void
    ) {
        guard let entry = entries.first else {
            completion(failure)
            return
        }
        forward(bindingId, entry: entry) { [weak self] result in
            var first = failure
            if case .failure(let refusal) = result, first == nil { first = refusal }
            self?.forwardEach(bindingId, entries.dropFirst(), failure: first, completion: completion)
        }
    }

    private func forward(
        _ bindingId: String, entry: ChannelServiceEntry, completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        let entryKey = Self.key(bindingId, entry.id)
        if let held = listening[entryKey] {
            completion(.success(held.port))
            return
        }
        let port: Int
        do {
            guard self.port(bindingId: bindingId, entry: entry) > 0 else {
                completion(.failure(.refusal("local_port_invalid", ["port": "0"])))
                return
            }
            port = try table.port(forEntry: entryKey, hubPort: entry.localPort, protocol: entry.protocol)
        } catch let refusal as ClientError {
            completion(.failure(refusal))
            return
        } catch {
            completion(.failure(.refusal("forward_failed", ["detail": "\(error)"])))
            return
        }
        if listening.values.contains(where: { $0.port == port && $0.protocol == entry.protocol }) {
            completion(.failure(.refusal("port_taken", ["port": "\(port)"])))
            return
        }
        let open: [String: JSONValue] = ["kind": .string(Channel.kindConnect), "id": .string(entry.id)]
        listen(
            bindingId, entryKey: entryKey, appKey: Self.key(bindingId, entry.appId), port: port,
            protocol: entry.protocol, open: open, completion: completion)
    }

    private func pick(
        _ bindingId: String, entryKey: String, rowKey: String, open: [String: JSONValue],
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        if let held = listening[entryKey] {
            completion(.success(held.port))
            return
        }
        do {
            let port = try table.pick(for: entryKey, protocol: "tcp")
            listen(
                bindingId, entryKey: entryKey, appKey: rowKey, port: port, protocol: "tcp", open: open,
                completion: completion)
        } catch let refusal as ClientError {
            completion(.failure(refusal))
        } catch {
            completion(.failure(.refusal("forward_failed", ["detail": "\(error)"])))
        }
    }

    private func listen(
        _ bindingId: String, entryKey: String, appKey: String, port: Int, protocol: String,
        open: [String: JSONValue], completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        forwarder.start(bindingId: bindingId, port: port, protocol: `protocol`, open: open) { [weak self] result in
            if case .success(let bound) = result {
                self?.listening[entryKey] = ForwardListener(
                    bindingId: bindingId, appKey: appKey, port: bound, protocol: `protocol`, open: open)
                ClientLog.info("forwarding \(Forward.bindHost):\(bound)/\(`protocol`) to \(entryKey) through the hub")
            }
            completion(result)
        }
    }

    private func open(
        bindingId: String, entry: ChannelServiceEntry, onOpen: @escaping (String) -> Void,
        completion: @escaping (ClientError?) -> Void
    ) {
        guard let held = listening[Self.key(bindingId, entry.id)],
            let target = ForwardWebTarget(entry.payload.text("url"))
        else {
            completion(nil)
            return
        }
        let address = "\(target.scheme)://\(Forward.bindHost):\(held.port)\(target.path)"
        guard entry.payload.flag("is_token_required") else {
            onOpen(address)
            completion(nil)
            return
        }
        material(bindingId, ["id": .string(entry.id)]) { result in
            switch result {
            case .failure(let refusal):
                completion(refusal)
            case .success(let answer):
                let token = answer.text("token")
                guard !token.isEmpty else {
                    completion(.refusal("web_token_missing"))
                    return
                }
                onOpen(Self.tokenUrl(address, token: token))
                completion(nil)
            }
        }
    }

    private func end(_ entryKey: String, why: String) {
        guard let held = listening.removeValue(forKey: entryKey) else { return }
        forwarder.stop(port: held.port, protocol: held.protocol)
        ClientLog.info("stopped forwarding \(Forward.bindHost):\(held.port)/\(held.protocol) to \(entryKey): \(why)")
        guard entryKey.hasSuffix("/" + Forward.panelEntry), var row = rows[entryKey] else { return }
        row.localPort = 0
        rows[entryKey] = row == ForwardRow() ? nil : row
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

    /// The entry an app's Open opens: its first `web` entry with an `http` or `https` address.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - app: The app.
    /// - Returns: The entry, or nil for an app with none.
    static func page(of hub: HubView, app: ChannelApp) -> ChannelServiceEntry? {
        entries(of: hub, app: app).first { $0.type == "web" && ForwardWebTarget($0.payload.text("url")) != nil }
    }

    /// An app's `web` and `port` entries, in the hub's order; a phone leaves the `ssh` ones out.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes the app.
    ///   - app: The app.
    /// - Returns: The entries.
    static func entries(of hub: HubView, app: ChannelApp) -> [ChannelServiceEntry] {
        hub.services.filter { $0.appId == app.id && ($0.type == "web" || $0.type == "port") }
    }

    /// The key of one app or entry.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - id: The app's or the entry's id.
    /// - Returns: `<binding>/<id>`.
    static func key(_ bindingId: String, _ id: String) -> String {
        "\(bindingId)/\(id)"
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
}
