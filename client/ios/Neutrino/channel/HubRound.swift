import Foundation

/// One connection round: every candidate address dialled at once, each with its own connect time; an address
/// that refuses is dialled again every second until its connect time ends, and one that does not answer is not
/// dialled again. The first socket to open on the pinned certificate wins and every other socket is closed
/// before any hello. Every call and every callback runs on the main queue.
final class HubRound {
    private let transport: HubTransport
    private let fingerprint: String
    private let clock: ClientClock
    private let onWin: (HubRoundDial) -> Void
    private let onLose: ([(url: String, refusal: ClientError)]) -> Void
    private var dials: [HubRoundDial] = []
    private var refusals: [(url: String, refusal: ClientError)] = []
    private var isEnded = false
    private var isNamePending = false
    private var nameTimer: ClientTimer?

    /// The address the hub's name resolved to, empty until it did.
    private(set) var nameUrl = ""

    /// Prepare a round.
    ///
    /// - Parameters:
    ///   - transport: How the hub is reached.
    ///   - fingerprint: The pinned SHA-256.
    ///   - clock: The connect times and the redials.
    ///   - onWin: Called with the address whose socket opened first; its socket is the caller's.
    ///   - onLose: Called with every address's refusal once all of them failed.
    init(
        transport: HubTransport, fingerprint: String, clock: ClientClock,
        onWin: @escaping (HubRoundDial) -> Void,
        onLose: @escaping ([(url: String, refusal: ClientError)]) -> Void
    ) {
        self.transport = transport
        self.fingerprint = fingerprint
        self.clock = clock
        self.onWin = onWin
        self.onLose = onLose
    }

    /// Whether the round has won, lost or been cancelled.
    var isOver: Bool { isEnded }

    /// Dial every address at once.
    ///
    /// - Parameter urls: The round's addresses.
    func start(urls: [String]) {
        for url in urls where !dials.contains(where: { $0.url == url }) { dial(url) }
        checkEnd()
    }

    /// Hold the round open for the hub's name, which is being resolved; it waits at most one connect time.
    func expectName() {
        isNamePending = true
        nameTimer = clock.schedule(after: Channel.connectTimeoutSeconds) { [weak self] in
            self?.nameResolved("")
        }
    }

    /// The hub's name resolved, or did not: its address joins the round.
    ///
    /// - Parameter url: The address on the name's address, or empty.
    func nameResolved(_ url: String) {
        guard isNamePending else { return }
        isNamePending = false
        nameTimer?.cancel()
        nameTimer = nil
        if !url.isEmpty, !isEnded, !dials.contains(where: { $0.url == url }) {
            nameUrl = url
            dial(url)
        }
        checkEnd()
    }

    /// End the round before its dials do: every socket is closed and nothing is called.
    func cancel() {
        guard !isEnded else { return }
        isEnded = true
        nameTimer?.cancel()
        for dial in dials { close(dial) }
    }

    private func dial(_ url: String) {
        let dial = HubRoundDial(url: url)
        dials.append(dial)
        connect(dial)
        dial.deadline = clock.schedule(after: Channel.connectTimeoutSeconds) { [weak self, weak dial] in
            guard let self, let dial, !self.isEnded, !dial.isSettled else { return }
            let late = ClientError.refusal(
                Channel.codeHubUnreachable,
                ["detail": "the address did not open in \(Int(Channel.connectTimeoutSeconds))s"])
            self.settle(dial, dial.lastRefusal ?? late)
        }
    }

    private func connect(_ dial: HubRoundDial) {
        let socket = transport.connect(baseUrl: dial.url, fingerprint: fingerprint)
        dial.socket = socket
        dial.attemptNanos = clock.uptimeNanos
        socket.onEvent = { [weak self, weak dial] event in
            guard let self, let dial else { return }
            self.take(event, on: dial)
        }
    }

    private func take(_ event: ChannelSocketEvent, on dial: HubRoundDial) {
        guard !isEnded, !dial.isSettled else { return }
        switch event {
        case .opened:
            win(dial)
        case .failed(let refusal, let isPortClosed):
            guard isPortClosed else {
                settle(dial, refusal)
                return
            }
            dial.lastRefusal = refusal
            dial.socket?.onEvent = nil
            dial.socket?.close(code: Channel.closeNormal)
            dial.socket = nil
            dial.redial = clock.schedule(after: Channel.redialIntervalSeconds) { [weak self, weak dial] in
                guard let self, let dial, !self.isEnded, !dial.isSettled else { return }
                self.connect(dial)
            }
        case .closed:
            settle(dial, .refusal(Channel.codeHubUnreachable, ["detail": "the socket did not open"]))
        case .text, .binary:
            break
        }
    }

    private func win(_ winner: HubRoundDial) {
        isEnded = true
        nameTimer?.cancel()
        winner.openNanos = clock.uptimeNanos &- winner.attemptNanos
        winner.cancelTimers()
        winner.socket?.onEvent = nil
        for dial in dials where dial !== winner { close(dial) }
        onWin(winner)
    }

    private func settle(_ dial: HubRoundDial, _ refusal: ClientError) {
        close(dial)
        refusals.append((dial.url, refusal))
        checkEnd()
    }

    private func close(_ dial: HubRoundDial) {
        dial.isSettled = true
        dial.cancelTimers()
        dial.socket?.onEvent = nil
        dial.socket?.close(code: Channel.closeNormal)
        dial.socket = nil
    }

    private func checkEnd() {
        guard !isEnded, !isNamePending, dials.allSatisfy(\.isSettled) else { return }
        isEnded = true
        onLose(refusals)
    }
}
