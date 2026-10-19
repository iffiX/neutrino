import Foundation

@testable import Neutrino

/// A Keychain in memory.
final class FakeSecretStore: SecretStore {
    private(set) var items: [String: Data] = [:]

    func read(account: String) -> Data? {
        items[account]
    }

    func write(account: String, data: Data) throws {
        items[account] = data
    }

    func remove(account: String) throws {
        items[account] = nil
    }
}
