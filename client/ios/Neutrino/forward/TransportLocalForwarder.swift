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
        bindingId: String, port: Int, protocol: String, open: [String: JSONValue], isBrowserOpened: Bool,
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        listen(bindingId: bindingId, host: Forward.bindHost, port: port, protocol: `protocol`, open: open) {
            [weak self] first in
            guard case .success(let number) = first, isBrowserOpened, let self else {
                completion(first)
                return
            }
            self.listen(
                bindingId: bindingId, host: Forward.bindHostIpv6, port: number, protocol: `protocol`, open: open
            ) { [weak self] second in
                if case .failure(let refusal) = second {
                    self?.close(host: Forward.bindHost, port: number, protocol: `protocol`)
                    completion(.failure(refusal))
                    return
                }
                completion(.success(number))
            }
        }
    }

    func stop(port: Int, protocol: String, isBrowserOpened: Bool) {
        close(host: Forward.bindHost, port: port, protocol: `protocol`)
        if isBrowserOpened { close(host: Forward.bindHostIpv6, port: port, protocol: `protocol`) }
    }

    private func listen(
        bindingId: String, host: String, port: Int, protocol: String, open: [String: JSONValue],
        completion: @escaping (Result<Int, ClientError>) -> Void
    ) {
        let fields: [String: JSONValue] = [
            "binding": .string(bindingId),
            "listen": .string("\(host):\(port)"),
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

    private func close(host: String, port: Int, protocol: String) {
        let fields: [String: JSONValue] = ["listen": .string("\(host):\(port)"), "protocol": .string(`protocol`)]
        transport.command("forward_stop", fields) { _ in }
    }
}
