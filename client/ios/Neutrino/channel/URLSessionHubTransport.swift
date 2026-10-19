import CryptoKit
import Foundation

/// The pinned transport over URLSession: TLS 1.2 and up, trusting the one fingerprint and nothing else, every
/// callback on the main queue.
final class URLSessionHubTransport: NSObject, HubTransport {
    private let lock = NSLock()
    private var pins: [ObjectIdentifier: String] = [:]
    private var untrusted: Set<ObjectIdentifier> = []
    private var sockets: [ObjectIdentifier: URLSessionChannelSocket] = [:]

    private lazy var requestSession = URLSession(
        configuration: Self.configuration(timeout: Channel.requestTimeoutSeconds), delegate: self,
        delegateQueue: .main)

    private lazy var socketSession = URLSession(
        configuration: Self.configuration(timeout: Channel.silenceTimeoutSeconds), delegate: self,
        delegateQueue: .main)

    func post(
        baseUrl: String, path: String, fingerprint: String, body: [String: JSONValue],
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        guard let url = URL(string: Self.trimmed(baseUrl) + path) else {
            completion(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the address does not read"])))
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = JSONValue.object(body).encoded()
        let box = URLSessionTaskKey()
        let task = requestSession.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self, let key = box.key else { return }
                let isUntrusted = self.forget(key)
                let answer = Self.answer(
                    data: data, response: response, error: error, isUntrusted: isUntrusted, baseUrl: baseUrl)
                completion(answer)
            }
        }
        box.key = ObjectIdentifier(task)
        pin(ObjectIdentifier(task), fingerprint)
        task.resume()
    }

    func connect(baseUrl: String, fingerprint: String) -> ChannelSocket {
        let address = Self.trimmed(baseUrl).replacingOccurrences(of: "https://", with: "wss://") + Channel.socketPath
        let task = socketSession.webSocketTask(with: URL(string: address) ?? URL(fileURLWithPath: "/"))
        task.maximumMessageSize = Channel.messageBytesMax
        let socket = URLSessionChannelSocket(task: task, baseUrl: baseUrl)
        let key = ObjectIdentifier(task)
        pin(key, fingerprint)
        sockets[key] = socket
        DispatchQueue.main.async { task.resume() }
        return socket
    }

    private func pin(_ key: ObjectIdentifier, _ fingerprint: String) {
        lock.lock()
        pins[key] = fingerprint
        lock.unlock()
    }

    private func isPinned(_ key: ObjectIdentifier, trust: SecTrust) -> Bool {
        lock.lock()
        let pinned = pins[key] ?? ""
        lock.unlock()
        guard !pinned.isEmpty, Self.fingerprint(of: trust) == pinned else {
            lock.lock()
            untrusted.insert(key)
            lock.unlock()
            return false
        }
        return true
    }

    /// Forget a finished task.
    ///
    /// - Parameter key: The task.
    /// - Returns: Whether its certificate was another than the pinned one.
    @discardableResult
    private func forget(_ key: ObjectIdentifier) -> Bool {
        sockets[key] = nil
        lock.lock()
        defer { lock.unlock() }
        pins[key] = nil
        return untrusted.remove(key) != nil
    }

    private static func configuration(timeout: Double) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.tlsMinimumSupportedProtocolVersion = .TLSv12
        configuration.timeoutIntervalForRequest = timeout
        configuration.waitsForConnectivity = false
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        return configuration
    }

    private static func trimmed(_ url: String) -> String {
        var text = url
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }

    private static func answer(
        data: Data?, response: URLResponse?, error: Error?, isUntrusted: Bool, baseUrl: String
    ) -> Result<[String: JSONValue], ClientError> {
        if isUntrusted { return .failure(.refusal(Channel.codeHubUntrusted, ["url": baseUrl])) }
        guard let response = response as? HTTPURLResponse else {
            let detail = error?.localizedDescription ?? "no answer"
            return .failure(.refusal(Channel.codeHubUnreachable, ["detail": detail]))
        }
        let document = data.flatMap { try? JSONValue.parse($0) }?.objectValue ?? [:]
        if (200..<300).contains(response.statusCode) { return .success(document) }
        let detail = document.object("detail")
        let code = detail.text("code")
        if !code.isEmpty { return .failure(.refused(code: code, params: detail.object("params"))) }
        if response.statusCode == 401 || response.statusCode == 403 {
            return .failure(.refusal(Channel.codeHubRefused))
        }
        return .failure(.refusal(Channel.codeHubUnreachable, ["detail": "the hub answered \(response.statusCode)"]))
    }

    /// The fingerprint of the certificate a server presented.
    ///
    /// - Parameter trust: The server's trust.
    /// - Returns: The SHA-256 of the leaf certificate's DER encoding, lower-case hex, or nil when there is none.
    static func fingerprint(of trust: SecTrust) -> String? {
        guard let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let leaf = chain.first else {
            return nil
        }
        let der = SecCertificateCopyData(leaf) as Data
        return SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
    }
}

extension URLSessionHubTransport: URLSessionWebSocketDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge) async
        -> (URLSession.AuthChallengeDisposition, URLCredential?)
    {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
            let trust = challenge.protectionSpace.serverTrust
        else { return (.cancelAuthenticationChallenge, nil) }
        guard isPinned(ObjectIdentifier(task), trust: trust) else { return (.cancelAuthenticationChallenge, nil) }
        return (.useCredential, URLCredential(trust: trust))
    }

    func urlSession(
        _ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?
    ) {
        sockets[ObjectIdentifier(webSocketTask)]?.opened()
    }

    func urlSession(
        _ session: URLSession, webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?
    ) {
        sockets[ObjectIdentifier(webSocketTask)]?.closedByHub(code: closeCode.rawValue)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let key = ObjectIdentifier(task)
        guard let socket = sockets[key] else { return }
        let isUntrusted = forget(key)
        let refusal: ClientError
        if isUntrusted {
            refusal = .refusal(Channel.codeHubUntrusted, ["url": socket.baseUrl])
        } else {
            let detail = error?.localizedDescription ?? "the socket closed"
            refusal = .refusal(Channel.codeHubUnreachable, ["detail": detail])
        }
        socket.failed(refusal, isPortClosed: (error as? URLError)?.code == .cannotConnectToHost)
    }
}
