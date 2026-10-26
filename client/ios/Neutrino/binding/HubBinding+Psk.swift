import CryptoKit
import Foundation

extension HubBinding {
    /// The psk a bound knock carries: the SHA-256 of the token, 64 lowercase hex characters.
    var psk: String {
        SHA256.hash(data: Data(token.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
