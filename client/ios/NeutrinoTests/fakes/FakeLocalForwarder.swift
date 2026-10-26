import Foundation

@testable import Neutrino

/// A forwarder that records each listener and answers with `refusal` when one is set.
final class FakeLocalForwarder: LocalForwarder {
    /// Every listener started: its hub, number, protocol and open record.
    private(set) var started: [(bindingId: String, port: Int, protocol: String, open: [String: JSONValue])] = []

    /// Every listener stopped.
    private(set) var stopped: [(port: Int, protocol: String)] = []

    /// The refusal every start answers with, nil to take every one.
    var refusal: ClientError?

    func start(
        bindingId: String, port: Int, protocol: String, open: [String: JSONValue],
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        if let refusal {
            completion(.failure(refusal))
            return
        }
        started.append((bindingId, port, `protocol`, open))
        completion(.success(port))
    }

    func stop(port: Int, protocol: String) {
        stopped.append((port, `protocol`))
    }
}
