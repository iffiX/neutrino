import Foundation

/// One channel socket over a `URLSessionWebSocketTask`, its events in order on the main queue.
final class URLSessionChannelSocket: ChannelSocket {
    /// The task under the socket.
    let task: URLSessionWebSocketTask

    /// The address the socket was opened to.
    let baseUrl: String

    private var isEnded = false

    var onEvent: ((ChannelSocketEvent) -> Void)?

    /// Wrap a task that is about to resume.
    ///
    /// - Parameters:
    ///   - task: The task.
    ///   - baseUrl: The hub's address.
    init(task: URLSessionWebSocketTask, baseUrl: String) {
        self.task = task
        self.baseUrl = baseUrl
    }

    @discardableResult
    func sendText(_ text: String) -> Bool {
        send(.string(text))
    }

    @discardableResult
    func sendBytes(_ bytes: Data) -> Bool {
        send(.data(bytes))
    }

    func close(code: Int) {
        guard !isEnded else { return }
        isEnded = true
        onEvent = nil
        task.cancel(with: URLSessionWebSocketTask.CloseCode(rawValue: code) ?? .normalClosure, reason: nil)
    }

    /// The upgrade finished on the pinned certificate: the socket reads from now on.
    func opened() {
        guard !isEnded else { return }
        onEvent?(.opened)
        receive()
    }

    /// The hub sent its close.
    ///
    /// - Parameter code: The close code.
    func closedByHub(code: Int) {
        guard !isEnded else { return }
        isEnded = true
        onEvent?(.closed(code: code))
    }

    /// The task ended without a close from the hub.
    ///
    /// - Parameters:
    ///   - refusal: Why.
    ///   - isPortClosed: Whether the host refused the connection.
    func failed(_ refusal: ClientError, isPortClosed: Bool) {
        guard !isEnded else { return }
        let code = task.closeCode.rawValue
        if code != URLSessionWebSocketTask.CloseCode.invalid.rawValue {
            closedByHub(code: code)
            return
        }
        isEnded = true
        onEvent?(.failed(refusal, isPortClosed: isPortClosed))
    }

    private func send(_ message: URLSessionWebSocketTask.Message) -> Bool {
        guard !isEnded else { return false }
        task.send(message) { [weak self] error in
            guard let self, let error else { return }
            DispatchQueue.main.async {
                self.failed(
                    .refusal(Channel.codeHubUnreachable, ["detail": error.localizedDescription]), isPortClosed: false)
            }
        }
        return true
    }

    private func receive() {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self, !self.isEnded else { return }
                switch result {
                case .success(.string(let text)):
                    self.onEvent?(.text(text))
                    self.receive()
                case .success(.data(let data)):
                    self.onEvent?(.binary(data))
                    self.receive()
                case .success:
                    self.receive()
                case .failure(let error):
                    self.failed(
                        .refusal(Channel.codeHubUnreachable, ["detail": error.localizedDescription]),
                        isPortClosed: false)
                }
            }
        }
    }
}
