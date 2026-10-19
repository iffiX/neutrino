import Foundation

/// Where the app keeps its secrets, one item per account name: the Keychain on the phone, a fake in tests.
protocol SecretStore: AnyObject {
    /// One item.
    ///
    /// - Parameter account: The item's name.
    /// - Returns: Its bytes, or nil when there is none or it cannot be read.
    func read(account: String) -> Data?

    /// Keep one item, replacing what it held.
    ///
    /// - Parameters:
    ///   - account: The item's name.
    ///   - data: Its bytes.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be written.
    func write(account: String, data: Data) throws

    /// Forget one item; an item that is not there changes nothing.
    ///
    /// - Parameter account: The item's name.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the item cannot be removed.
    func remove(account: String) throws
}
