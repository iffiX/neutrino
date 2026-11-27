import Foundation

@testable import Neutrino

/// A forwarder that records each listener and answers with `refusal` when one is set.
final class FakeLocalForwarder: LocalForwarder {
    /// Every listener started: its hub, number, protocol and open record.
    private(set) var started: [(bindingId: String, port: Int, protocol: String, open: [String: JSONValue])] = []

    /// Whether a browser opens each listener started, in the same order.
    private(set) var browserStarts: [Bool] = []

    /// Every listener stopped.
    private(set) var stopped: [(port: Int, protocol: String)] = []

    /// Whether each listener stopped also listened on `[::1]`, in the same order.
    private(set) var browserStops: [Bool] = []

    /// The refusal every start answers with, nil to take every one.
    var refusal: ClientError?

    func start(
        bindingId: String, port: Int, protocol: String, open: [String: JSONValue], isBrowserOpened: Bool,
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        if let refusal {
            completion(.failure(refusal))
            return
        }
        started.append((bindingId, port, `protocol`, open))
        browserStarts.append(isBrowserOpened)
        completion(.success(port))
    }

    func stop(port: Int, protocol: String, isBrowserOpened: Bool) {
        stopped.append((port, `protocol`))
        browserStops.append(isBrowserOpened)
    }
}
