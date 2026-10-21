import Foundation

/// The share logins, by share key `<binding>/<entry>`: the kept ones in one Keychain item, and the ones given
/// until the app quits in memory. An item that is missing or does not read holds no login.
final class ShareLoginStore {
    private let secrets: SecretStore
    private var kept: [String: ShareLogin]
    private var forNow: [String: ShareLogin] = [:]

    /// Read the kept logins.
    ///
    /// - Parameter secrets: Where the item lives.
    init(secrets: SecretStore) {
        self.secrets = secrets
        let data = secrets.read(account: SharePage.loginsAccount)
        kept = data.flatMap { try? JSONDecoder().decode([String: ShareLogin].self, from: $0) } ?? [:]
    }

    /// The keys of the shares with a login held, kept or until the app quits.
    var keys: Set<String> { Set(kept.keys).union(forNow.keys) }

    /// The login of one share.
    ///
    /// - Parameter key: The share's key.
    /// - Returns: The login, or nil when none is held.
    func login(_ key: String) -> ShareLogin? {
        forNow[key] ?? kept[key]
    }

    /// Whether a share's login is kept in the Keychain.
    ///
    /// - Parameter key: The share's key.
    /// - Returns: True when it is.
    func isKept(_ key: String) -> Bool {
        kept[key] != nil
    }

    /// Hold a share's login: in the Keychain, or until the app quits.
    ///
    /// - Parameters:
    ///   - key: The share's key.
    ///   - login: The login.
    ///   - isKept: Whether it goes into the Keychain.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func put(_ key: String, _ login: ShareLogin, isKept: Bool) throws {
        forNow[key] = nil
        var next = kept
        next[key] = isKept ? login : nil
        if !isKept { forNow[key] = login }
        if next != kept { try write(next) }
    }

    /// Forget a share's login.
    ///
    /// - Parameter key: The share's key.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func forget(_ key: String) throws {
        forNow[key] = nil
        guard kept[key] != nil else { return }
        var next = kept
        next[key] = nil
        try write(next)
    }

    /// A hub is left: the logins of its shares go.
    ///
    /// - Parameter bindingId: The hub.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func forget(bindingId: String) throws {
        let prefix = "\(bindingId)/"
        forNow = forNow.filter { !$0.key.hasPrefix(prefix) }
        let next = kept.filter { !$0.key.hasPrefix(prefix) }
        if next.count != kept.count { try write(next) }
    }

    private func write(_ next: [String: ShareLogin]) throws {
        if next.isEmpty {
            try secrets.remove(account: SharePage.loginsAccount)
        } else {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            let data: Data
            do {
                data = try encoder.encode(next)
            } catch {
                throw ClientError.refusal(Channel.codeClientInternal, ["error": "\(error)"])
            }
            try secrets.write(account: SharePage.loginsAccount, data: data)
        }
        kept = next
    }
}
