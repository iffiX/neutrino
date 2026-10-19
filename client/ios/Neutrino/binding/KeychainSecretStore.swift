import Foundation
import Security

/// The phone's Keychain: one generic password per account name, readable after the first unlock and never
/// moved to another device.
final class KeychainSecretStore: SecretStore {
    private let service: String

    /// Keep secrets under one Keychain service.
    ///
    /// - Parameter service: The service every item is filed under.
    init(service: String) {
        self.service = service
    }

    func read(account: String) -> Data? {
        var query = base(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess else { return nil }
        return item as? Data
    }

    func write(account: String, data: Data) throws {
        let found = SecItemUpdate(base(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if found == errSecSuccess { return }
        guard found == errSecItemNotFound else { throw failure(found) }
        var item = base(account)
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let added = SecItemAdd(item as CFDictionary, nil)
        guard added == errSecSuccess else { throw failure(added) }
    }

    func remove(account: String) throws {
        let status = SecItemDelete(base(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw failure(status) }
    }

    private func base(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private func failure(_ status: OSStatus) -> ClientError {
        .refusal(Channel.codeClientInternal, ["error": "the Keychain answered \(status)"])
    }
}
