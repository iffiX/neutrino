import Foundation

/// The account one share is opened with.
struct ShareLogin: Codable, Equatable {
    /// The account's name.
    let user: String

    /// Its password.
    let password: String
}
