import Foundation

/// The file entries' shares of the app core: each row's Open, the logins held, and the one share the share page
/// shows. A login is held only once the share took it; `share_login_rejected` forgets it. The open share closes
/// when the page goes back from its root, when its hub is left, and when its hub no longer lists its entry.
/// Every call runs on the main queue.
final class ShareSessions {
    private let logins: ShareLoginStore
    private let makeClient: () -> ShareClient
    private let openConnect: (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>
    private let directory: URL
    private var opening: ShareSession?
    private var channelless: Set<String> = []

    /// Called after every change of a row, a login or the page.
    var onChange: (() -> Void)?

    /// The share the page shows, nil while the page is closed.
    private(set) var session: ShareSession?

    /// Every row with a job or a code, by share key `<binding>/<entry>`.
    private(set) var rows: [String: ShareRow] = [:] {
        didSet {
            if rows != oldValue { onChange?() }
        }
    }

    /// Prepare the shares.
    ///
    /// - Parameters:
    ///   - secrets: Where the kept logins live.
    ///   - makeClient: Makes the SMB client of one connection.
    ///   - openConnect: Opens one `connect` stream on a hub, by binding id and the stream's arguments.
    ///   - directory: Where the shares' files go in the app's temporary directory.
    init(
        secrets: SecretStore, makeClient: @escaping () -> ShareClient,
        openConnect: @escaping (String, [String: JSONValue]) -> Result<ChannelStream, ClientError>,
        directory: URL = FileManager.default.temporaryDirectory.appendingPathComponent(SharePage.temporaryDirectory)
    ) {
        logins = ShareLoginStore(secrets: secrets)
        self.makeClient = makeClient
        self.openConnect = openConnect
        self.directory = directory
    }

    /// The keys of the shares with a login held.
    var heldLogins: Set<String> { logins.keys }

    /// Press Open on a share with a login held: it logs in, then the page opens at the share's root.
    ///
    /// - Parameter target: The share.
    func open(_ target: ShareTarget) {
        guard let login = logins.login(target.id) else { return }
        start(target, login: login, isKept: nil)
    }

    /// Press Connect in the login sheet: it logs in, the login is held once the share took it, then the page
    /// opens at the share's root.
    ///
    /// - Parameters:
    ///   - target: The share.
    ///   - login: The account.
    ///   - isKept: Whether the login goes into the Keychain, or is held until the app quits.
    func logIn(_ target: ShareTarget, login: ShareLogin, isKept: Bool) {
        start(target, login: login, isKept: isKept)
    }

    /// The second press on Forget password, and a login the share rejected: the share's login goes.
    ///
    /// - Parameter key: The share's key.
    func forgetLogin(_ key: String) {
        do {
            try logins.forget(key)
        } catch {
            ClientLog.info("the share login of \(key) was not forgotten: \(error)")
        }
        onChange?()
    }

    /// The back arrow on the share page: up one folder, and at the root the page closes.
    func back() {
        guard let session, !session.back() else { return }
        closeSession()
    }

    /// Take one round of the hubs' state: the forward of a hub without a channel accepts nothing, and the open
    /// share closes when its hub is gone or serves this phone without its entry.
    ///
    /// - Parameter hubs: Every hub's view.
    func take(_ hubs: [HubView]) {
        channelless = Set(hubs.filter { $0.connectedAddress.isEmpty }.map(\.binding.id))
        for each in [opening, session].compactMap({ $0 }) {
            each.channelChanged(isOpen: !channelless.contains(each.target.bindingId))
        }
        guard let session else { return }
        let hub = hubs.first { $0.binding.id == session.target.bindingId }
        if let hub, !hub.isConnected || hub.services.contains(where: { $0.id == session.target.entryId }) { return }
        closeSession()
    }

    /// A hub is being left: its open share closes, and its rows and its logins go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        if opening?.target.bindingId == bindingId {
            opening?.close()
            opening = nil
        }
        if session?.target.bindingId == bindingId { closeSession() }
        rows = rows.filter { !$0.key.hasPrefix("\(bindingId)/") }
        do {
            try logins.forget(bindingId: bindingId)
        } catch {
            ClientLog.info("the share logins of \(bindingId) were not forgotten: \(error)")
        }
        onChange?()
    }

    /// A refresh: every row's code goes, and the open share reads its folder again.
    func refresh() {
        rows = rows.compactMapValues { $0.isOpening ? ShareRow(isOpening: true) : nil }
        session?.refresh()
    }

    /// The time in the background is ending: a login being tried stops, and the open share's transfers are cut
    /// and its connection and forward close.
    func suspend() {
        if let opening {
            opening.close()
            rows[opening.target.id] = nil
            self.opening = nil
        }
        session?.suspend()
    }

    /// The app came back to the foreground: the open share logs in again and reads its folder again.
    func foreground() {
        guard let session else { return }
        session.resume { [weak self] refusal in
            if refusal?.code == SharePage.codeLoginRejected { self?.forgetLogin(session.target.id) }
        }
    }

    private func start(_ target: ShareTarget, login: ShareLogin, isKept: Bool?) {
        let key = target.id
        guard opening == nil, rows[key]?.isOpening != true else {
            ClientLog.info("a login runs on \(key); the press is dropped")
            return
        }
        rows[key] = ShareRow(isOpening: true)
        let session = ShareSession(
            target: target, login: login, makeClient: makeClient,
            openConnect: { [openConnect] in
                openConnect(target.bindingId, ["id": .string(target.entryId)])
            },
            directory: directory)
        session.channelChanged(isOpen: !channelless.contains(target.bindingId))
        opening = session
        session.start { [weak self, weak session] refusal in
            guard let self, let session, self.opening === session else { return }
            self.opening = nil
            if let refusal {
                session.close()
                if refusal.code == SharePage.codeLoginRejected { self.forgetLogin(key) }
                self.rows[key] = ShareRow(error: refusal)
                return
            }
            if let isKept {
                do {
                    try self.logins.put(key, login, isKept: isKept)
                } catch let refusal as ClientError {
                    session.close()
                    self.rows[key] = ShareRow(error: refusal)
                    return
                } catch {
                    session.close()
                    self.rows[key] = ShareRow(error: .refusal(Channel.codeClientInternal, ["error": "\(error)"]))
                    return
                }
            }
            self.rows[key] = nil
            self.closeSession()
            session.onChange = { [weak self] in self?.onChange?() }
            self.session = session
            session.reload()
            self.onChange?()
        }
    }

    private func closeSession() {
        guard let session else { return }
        self.session = nil
        session.onChange = nil
        session.close()
        onChange?()
    }
}
