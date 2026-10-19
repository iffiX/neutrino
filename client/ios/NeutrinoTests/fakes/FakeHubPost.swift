import Foundation

@testable import Neutrino

/// One request a test answers.
struct FakeHubPost {
    let baseUrl: String
    let path: String
    let body: [String: JSONValue]
    let completion: (Result<[String: JSONValue], ClientError>) -> Void
}
