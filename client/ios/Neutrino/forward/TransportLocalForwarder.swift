import Foundation

/// The loopback listeners the transport holds, started with `forward_start` and closed with `forward_stop`.
final class TransportLocalForwarder: LocalForwarder {
    private let transport: ClientTransport

    /// Hold listeners in the transport.
    ///
    /// - Parameter transport: The transport's local channel.
    init(transport: ClientTransport) {
        self.transport = transport
    }

    func start(
        bindingId: String, port: Int, protocol: String, open: [String: JSONValue],
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        let fields: [String: JSONValue] = [
            "binding": .string(bindingId),
            "listen": .string("\(Forward.bindHost):\(port)"),
            "protocol": .string(`protocol`),
            "open": .object(open),
        ]
        transport.command("forward_start", fields) { result in
            switch result {
            case .failure(let refusal):
                completion(.failure(refusal))
            case .success(let answer):
                let bound = answer.text("listen").split(separator: ":").last.flatMap { Int($0) } ?? port
                completion(.success(bound))
            }
        }
    }

    func stop(port: Int, protocol: String) {
        let fields: [String: JSONValue] = [
            "listen": .string("\(Forward.bindHost):\(port)"), "protocol": .string(`protocol`),
        ]
        transport.command("forward_stop", fields) { _ in }
    }
}
