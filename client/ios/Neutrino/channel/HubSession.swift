import Foundation

/// One hub's channel, run by the transport the app embeds: the binding's ticket spent with the transport's
/// `join`, then `dial` with every candidate address and its path, the `hello` on each session the transport opens,
/// the state taken and the reports sent, and the row's state from the transport's events. Every call runs on the
/// main queue.
///
/// A round dials the hub's address on each of its virtual networks, the address the hub's name resolves to, and
/// the binding's addresses, each with the path it reaches the hub by. The view is `connecting` while a round
/// dials, `connected` from the `welcome`, and `waiting` with a `HubWaitReason` otherwise, counting down to the next
/// round the transport names. Every address failing waits as `hub_silent`, or as `no_network` while the phone has
/// no network; `hub_untrusted` waits 60 s; `binding_unknown`, a protocol refusal and `replaced` wait for a person.
/// A session that ends with no refusal is dialled again at once by the transport. A session the transport moved to
/// a better path is greeted again, and the channel stays connected. The live session sends a `ping` frame every
/// 20 s and once after each welcome, and the `pong` echoing its nonce sets `rttMs`.
///
/// A binding whose ticket is unspent spends it with the transport's `join`; a refusal of the ticket is
/// `join_refused` with its code, and no round runs after it, except `admission_paused`, after which the join runs
/// again once `retry_after_s` has passed. A binding of 0.5's shape is `join_refused` with `hub_key_missing`.
final class HubSession {
    /// The binding the session is for, and the name the transport knows it by.
    let bindingId: String

    private let store: BindingStore
    private let transport: ClientTransport
    private let machine: ClientMachine
    private let clock: ClientClock
    private let resolveHubName: (@escaping (String?) -> Void) -> Void
    private let localNetworks: () -> [ChannelLocalNetwork]
    private let hasNetwork: () -> Bool
    private let onJoined: (String, String) -> Void
    private let onWelcomed: (String, String) -> Void
    private let writeLog: (String) -> Void
    private var isRunning = false
    private var isSuspended = false
    private var isJoining = false
    private var isLive = false
    private var held: HubWaitReason?
    private var backoff = Channel.backoffMinSeconds
    private var stateHash = ""
    private var serverPaths: [String: ChannelPath] = [:]
    private var sessionAddress = ""
    private var dialled: [ChannelCandidate]?
    private var waitTimer: ClientTimer?
    private var refreshTimer: ClientTimer?
    private var countdown: ClientTimer?
    private var reportTimer: ClientTimer?
    private var pingTimer: ClientTimer?
    private var pingNonce = ""
    private var pingSentNanos: UInt64 = 0
    // The control_unavailable refusals since the line at unavailableLoggedAt. It is nil outside a run.
    private var unavailableCount = 0
    private var unavailableLoggedAt: Double?
    private var requests: [String: (Result<[String: JSONValue], ClientError>) -> Void] = [:]

    /// Called with the view after each change.
    var onChange: ((HubView) -> Void)?

    /// The hub as the pages read it.
    private(set) var view: HubView {
        didSet {
            if view != oldValue { onChange?(view) }
        }
    }

    /// Prepare the session of one binding.
    ///
    /// - Parameters:
    ///   - bindingId: The binding.
    ///   - store: Where the binding is kept and noted.
    ///   - transport: The transport's local channel.
    ///   - machine: What this phone says about itself.
    ///   - clock: The time and the timers.
    ///   - resolveHubName: Calls back with the IPv4 address `hub.neutrino.internal` resolves to here, or nil.
    ///   - localNetworks: The networks this phone holds an address in, read for each candidate's path.
    ///   - hasNetwork: Whether the phone has a network at all, read when a round ended with no session.
    ///   - onJoined: Called with the binding's id and the hub's id for it once its ticket is spent.
    ///   - onWelcomed: Called with the binding's id and the hub id after each welcome, before the binding takes that
    ///     id and before the session's first state is read.
    ///   - writeLog: Writes one log line.
    init(
        bindingId: String, store: BindingStore, transport: ClientTransport, machine: ClientMachine, clock: ClientClock,
        resolveHubName: @escaping (@escaping (String?) -> Void) -> Void,
        localNetworks: @escaping () -> [ChannelLocalNetwork], hasNetwork: @escaping () -> Bool,
        onJoined: @escaping (String, String) -> Void, onWelcomed: @escaping (String, String) -> Void = { _, _ in },
        writeLog: @escaping (String) -> Void = { ClientLog.info($0) }
    ) {
        self.bindingId = bindingId
        self.store = store
        self.transport = transport
        self.machine = machine
        self.clock = clock
        self.resolveHubName = resolveHubName
        self.localNetworks = localNetworks
        self.hasNetwork = hasNetwork
        self.onJoined = onJoined
        self.onWelcomed = onWelcomed
        self.writeLog = writeLog
        view = HubView(binding: store.get(bindingId) ?? HubBinding(id: bindingId, gatewayUrl: "", token: ""))
    }

    /// Join and dial the hub, and follow the transport's events until `stop()`.
    func start() {
        guard !isRunning else { return }
        isRunning = true
        transport.subscribe(bindingId) { [weak self] event in self?.take(event) }
        begin()
    }

    /// Stop following the hub, and tell the transport to dial it no more.
    func stop() {
        isRunning = false
        quiet()
        transport.unsubscribe(bindingId)
        transport.command("undial", ["binding": .string(bindingId)]) { _ in }
    }

    /// The app is about to be suspended: the session closes and nothing is dialled until `foreground()`.
    func suspend() {
        isSuspended = true
        quiet()
        transport.command("undial", ["binding": .string(bindingId)]) { _ in }
        if held == nil || held == .noNetwork { view = dialling(view) }
    }

    /// The app came back to the foreground: the hub is dialled again at once, with no backoff.
    func foreground() {
        isSuspended = false
        backoff = Channel.backoffMinSeconds
        if held == .noNetwork { held = nil }
        begin()
    }

    /// Take the binding back from a client that replaced this one, and dial now.
    func reconnect() {
        guard held == .replaced else { return }
        held = nil
        backoff = Channel.backoffMinSeconds
        view = dialling(view)
        dial(isForced: true)
    }

    /// A network changed: the phone's connectivity changed, a VPN another app runs came or went, or the hub's
    /// state named other addresses. A hub that waits for a person, or for the hub's admission, runs nothing; any
    /// other hub dials its candidates again and starts a round now, beside the live session when there is one,
    /// with the backoff at its floor.
    func networkChanged() {
        switch held {
        case nil: break
        case .noNetwork?: held = nil
        default: return
        }
        if view.waitReason == .disabled || view.waitReason == .admissionPaused { return }
        backoff = Channel.backoffMinSeconds
        roundNow()
    }

    /// A person pressed refresh: the hub is asked again. A connected hub gets a report with `is_refresh`; a hub
    /// with no live session runs a round now. A replaced or disabled hub, or one that waits only for Leave, takes
    /// no refresh. The refresh ends on a state frame, a code, or after 10 s.
    ///
    /// - Returns: Whether the hub entered refreshing, or already was.
    func refresh() -> Bool {
        let isStopped = held == .replaced || held == .unknownDevice || held == .joinRefused
        if isStopped || view.isDisabled { return false }
        if view.jobs.isRefreshing { return true }
        view.jobs.isRefreshing = true
        refreshTimer?.cancel()
        refreshTimer = clock.schedule(after: Channel.refreshTimeoutSeconds) { [weak self] in
            self?.refreshTimer = nil
            self?.view.jobs.isRefreshing = false
        }
        if isLive {
            report(isRefresh: true)
        } else {
            if held == .tooOld || held == .noNetwork { held = nil }
            backoff = Channel.backoffMinSeconds
            roundNow()
        }
        return true
    }

    /// Open one stream on the live session, on a local connection of its own.
    ///
    /// - Parameters:
    ///   - open: The stream's `open` record, `{kind, ...args}`.
    ///   - carriage: What it carries after its `accept`.
    /// - Returns: The stream, or `hub_unreachable` while the hub is not connected.
    func openStream(_ open: [String: JSONValue], carriage: TransportStream.Carriage) -> Result<
        TransportStream, ClientError
    > {
        guard isLive else {
            return .failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"]))
        }
        return transport.open(bindingId, open: open, carriage: carriage)
    }

    /// What the hub hands this phone on a `service` frame: an entry's material for `{id}`, the panel's one-time
    /// `{token}` for `{is_panel: true}`. The material is logged nowhere.
    ///
    /// - Parameters:
    ///   - args: The frame's arguments.
    ///   - completion: Called with the reply's params, or its refusal.
    func openService(
        args: [String: JSONValue], completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        ask({ ChannelFrames.service(request: $0, args: args) }, completion: completion)
    }

    /// Set whether a kept shell stays and whether others can attach to it.
    ///
    /// - Parameters:
    ///   - sessionId: The session.
    ///   - isPersistent: Whether it outlives every window.
    ///   - isShared: Whether every client with terminal rights on the machine lists it.
    ///   - completion: Called with the reply, or its refusal.
    func persist(
        sessionId: String, isPersistent: Bool, isShared: Bool,
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        ask(
            {
                ChannelFrames.persist(request: $0, sessionId: sessionId, isPersistent: isPersistent, isShared: isShared)
            }, completion: completion)
    }

    /// End a kept shell and every program in it.
    ///
    /// - Parameters:
    ///   - sessionId: The session.
    ///   - completion: Called with the reply, or its refusal.
    func stopSession(_ sessionId: String, completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void) {
        ask({ ChannelFrames.stopSession(request: $0, sessionId: sessionId) }, completion: completion)
    }

    private func ask(
        _ frameOf: (String) -> [String: JSONValue],
        completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        guard isLive else {
            completion(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"])))
            return
        }
        let request = UUID().uuidString
        let frame = frameOf(request)
        let type = frame.text("type")
        requests[request] = { [weak self] result in
            if case .failure(let refusal) = result {
                self?.log("the hub refused a \(type): \(refusal.code)")
            }
            completion(result)
        }
        guard transport.frame(bindingId, frame) else {
            requests[request] = nil
            completion(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the transport is gone"])))
            return
        }
        clock.schedule(after: Channel.streamTimeoutSeconds) { [weak self] in
            guard let call = self?.requests.removeValue(forKey: request) else { return }
            call(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the hub did not answer"])))
        }
    }

    private func begin() {
        guard isRunning, !isSuspended, let binding = store.get(bindingId) else { return }
        if binding.isKeyMissing {
            hold(.joinRefused, .refusal(Channel.codeHubKeyMissing))
            return
        }
        if binding.isPending {
            join()
        } else {
            dial(isForced: true)
        }
    }

    private func quiet() {
        waitTimer?.cancel()
        waitTimer = nil
        countdown?.cancel()
        countdown = nil
        dialled = nil
        endLive()
    }

    private func roundNow() {
        if isJoining {
            waitTimer?.cancel()
            waitTimer = nil
            join()
            return
        }
        dial(isForced: false) { [weak self] in
            guard let self else { return }
            self.transport.command("round", ["binding": .string(self.bindingId)]) { _ in }
        }
    }

    private func join() {
        guard isRunning, !isSuspended, let binding = store.get(bindingId), binding.isPending else {
            isJoining = false
            return
        }
        isJoining = true
        view = dialling(view)
        candidates(binding) { [weak self] candidates in
            guard let self, self.isRunning, !self.isSuspended else { return }
            var fields = ChannelFrames.join(ticket: binding.ticket, machine: self.machine)
            fields["binding"] = .string(self.bindingId)
            fields["hub_key"] = .string(binding.hubKey)
            fields["private_key"] = .string(binding.privateKey)
            fields["addresses"] = .array(candidates.map { .string($0.address) })
            self.transport.command("join", fields, timeout: Transport.joinTimeoutSeconds) { [weak self] result in
                self?.joinAnswered(result)
            }
        }
    }

    private func joinAnswered(_ result: Result<[String: JSONValue], ClientError>) {
        guard isRunning, !isSuspended else { return }
        switch result {
        case .success(let answer):
            isJoining = false
            if spend(answer) {
                dial(isForced: true)
            } else {
                hold(.joinRefused, .refusal("enroll_no_token"))
            }
        case .failure(let refusal):
            let wait: Double
            switch refusal.code {
            case Channel.codeHubUntrusted:
                wait = waitFor(.untrusted, refusal, Channel.backoffMaxSeconds)
            case Channel.codeAdmissionPaused:
                let retry = refusal.params["retry_after_s"]?.intValue.map(Double.init) ?? Channel.backoffMaxSeconds
                wait = waitFor(.admissionPaused, refusal, max(retry, 1))
            case _ where Channel.roundSilentCodes.contains(refusal.code):
                wait = silent(refusal, nextRound: nil)
            case _ where Channel.roundRetriedCodes.contains(refusal.code):
                wait = waitFor(HubWaitReason.hubSilent, refusal, Channel.backoffMaxSeconds)
            default:
                isJoining = false
                hold(.joinRefused, refusal)
                return
            }
            waitTimer?.cancel()
            waitTimer = clock.schedule(after: wait) { [weak self] in
                self?.waitTimer = nil
                self?.join()
            }
        }
    }

    private func spend(_ answer: [String: JSONValue]) -> Bool {
        let id = answer.text("binding_id")
        let token = answer.text("token")
        guard !id.isEmpty, !token.isEmpty else { return false }
        guard
            let kept = try? store.update(
                bindingId,
                { binding in
                    binding.hubBindingId = id
                    binding.token = token
                    binding.ticket = ""
                })
        else { return false }
        view.binding = kept
        log("joined the hub as \(id)")
        onJoined(bindingId, id)
        return true
    }

    private func dial(isForced: Bool, then: (() -> Void)? = nil) {
        guard isRunning, !isSuspended, let binding = store.get(bindingId), !binding.isPending, !binding.isKeyMissing,
            held != .replaced
        else { return }
        candidates(binding) { [weak self] candidates in
            guard let self, self.isRunning, !self.isSuspended else { return }
            guard isForced || candidates != self.dialled else {
                then?()
                return
            }
            self.dialled = candidates
            let fields: [String: JSONValue] = [
                "binding": .string(self.bindingId),
                "hub_key": .string(binding.hubKey),
                "private_key": .string(binding.privateKey),
                "psk": .string(binding.psk),
                "role": .string(Client.role),
                "protocol": .int(Channel.PROTOCOL),
                "candidates": .array(
                    candidates.map { .object(["address": .string($0.address), "path": .string($0.path)]) }),
            ]
            self.transport.command("dial", fields) { [weak self] result in
                guard let self else { return }
                if case .failure(let refusal) = result {
                    self.dialled = nil
                    self.log("the transport did not take the dial: \(refusal.code)")
                    if !self.isLive {
                        let wait = self.silent(refusal, nextRound: nil)
                        self.waitTimer?.cancel()
                        self.waitTimer = self.clock.schedule(after: wait) { [weak self] in
                            self?.waitTimer = nil
                            self?.dial(isForced: true)
                        }
                    }
                }
                then?()
            }
        }
    }

    private func candidates(_ binding: HubBinding, completion: @escaping ([ChannelCandidate]) -> Void) {
        let stored = binding.storedUrls.filter { $0.hasPrefix(Channel.addressScheme + "://") }
        let finish: (String) -> Void = { [weak self] nameUrl in
            guard let self else { return }
            var seen = Set<String>()
            let urls = (binding.overlayUrls.map(\.url) + [nameUrl] + stored).filter { url in
                !url.isEmpty && seen.insert(url).inserted
            }
            let networks = self.localNetworks()
            completion(
                urls.map { url in
                    let path = ChannelPath.of(
                        url: url, overlays: binding.overlays, serverPaths: self.serverPaths, localNetworks: networks)
                    return ChannelCandidate(address: url, path: path.rawValue)
                })
        }
        guard let first = stored.first else {
            finish("")
            return
        }
        resolveHubName { address in
            finish(address.map { ChannelAddress.url(first, onHost: $0) } ?? "")
        }
    }

    private func take(_ event: TransportEvent) {
        guard isRunning, !isSuspended else { return }
        switch event {
        case .sessionOpen(let address, let path, let handshakeMs):
            open(address: address, path: path, handshakeMs: handshakeMs)
        case .frame(let frame):
            takeFrame(frame)
        case .roundEnd(let refusal, let nextRound):
            roundEnded(refusal ?? .refusal(Channel.codeHubUnreachable), nextRound: nextRound)
        case .sessionEnd(let refusal):
            sessionEnded(refusal)
        case .restarted:
            endLive()
            view = dialling(view)
            dial(isForced: true)
        }
    }

    private func open(address: String, path: String, handshakeMs: Int) {
        guard let binding = store.get(bindingId) else { return }
        if held == .tooOld || held == .noNetwork { held = nil }
        sessionAddress = address
        let what = isLive ? "the channel moves to" : "a session opened at"
        log("\(what) \(address) (\(path)) after a \(handshakeMs) ms handshake")
        transport.frame(bindingId, ChannelFrames.hello(binding: binding, machine: machine))
    }

    private func takeFrame(_ frame: [String: JSONValue]) {
        switch ChannelInbound.decode(frame) {
        case .welcome(let welcome):
            if welcome.role == Client.hubRole { welcomed(welcome) }
        case .state(let state):
            takeState(state)
            report()
        case .reply(let request, let result):
            requests.removeValue(forKey: request)?(result)
        case .pong(let nonce):
            takePong(nonce)
        case .refused(let refusal):
            refused(refusal)
        case .unknown:
            break
        }
    }

    private func welcomed(_ welcome: ChannelWelcome) {
        if unavailableLoggedAt != nil {
            let refused =
                unavailableCount > 0
                ? "; refused \(Channel.codeControlUnavailable) \(unavailableCount) times since the last line" : ""
            log("the hub welcomed this client\(refused)")
            unavailableCount = 0
            unavailableLoggedAt = nil
        }
        onWelcomed(bindingId, welcome.id)
        isLive = true
        backoff = Channel.backoffMinSeconds
        countdown?.cancel()
        countdown = nil
        let address = sessionAddress
        note { binding in
            if !address.isEmpty { binding.gatewayUrl = address }
            binding.hubId = welcome.id
            binding.hubName = welcome.name
        }
        view.connection = .connected
        if view.waitReason != .disabled { view.waitReason = nil }
        view.waitRefusal = nil
        view.nextRoundAt = 0
        view.software = welcome.software
        view.connectedAddress = address
        view.hasConnected = true
        report(isRefresh: view.jobs.isRefreshing)
        pingNow()
        if reportTimer == nil { scheduleReport() }
    }

    private func refused(_ refusal: ClientError) {
        log("the hub refused the session: \(refusal.code)")
        switch refusal.code {
        case Channel.codeReplaced: held = .replaced
        case Channel.codeBindingUnknown: held = .unknownDevice
        case Channel.codeProtocolTooOld, Channel.codeProtocolTooNew: held = .tooOld
        default: break
        }
    }

    private func roundEnded(_ refusal: ClientError, nextRound: Double) {
        endRefresh()
        switch refusal.code {
        case Channel.codeHubUntrusted: _ = waitFor(.untrusted, refusal, nextRound)
        case Channel.codeBindingUnknown: hold(.unknownDevice, refusal)
        case Channel.codeReplaced: hold(.replaced, refusal)
        case Channel.codeProtocolTooOld, Channel.codeProtocolTooNew: hold(.tooOld, refusal)
        default: _ = silent(refusal, nextRound: nextRound)
        }
    }

    private func sessionEnded(_ refusal: ClientError?) {
        endLive()
        if refusal?.code == Channel.codeReplaced || held == .replaced {
            hold(.replaced, refusal)
        } else if refusal?.code == Channel.codeBindingUnknown || held == .unknownDevice {
            hold(.unknownDevice, refusal)
        } else if let refusal,
            [Channel.codeProtocolTooOld, Channel.codeProtocolTooNew].contains(refusal.code) || held == .tooOld
        {
            hold(.tooOld, refusal)
        } else if let refusal {
            _ = waitFor(.hubSilent, refusal, Channel.backoffMaxSeconds)
        } else {
            view = dialling(view)
        }
    }

    private func endLive() {
        let wasLive = isLive || !view.connectedAddress.isEmpty
        isLive = false
        reportTimer?.cancel()
        reportTimer = nil
        pingTimer?.cancel()
        pingTimer = nil
        pingNonce = ""
        let pending = requests
        requests = [:]
        for (_, call) in pending {
            call(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "the session ended"])))
        }
        guard wasLive else { return }
        view.connection = .connecting
        view.connectedAddress = ""
        view.rttMs = nil
        if view.waitReason == .disabled { view.waitReason = nil }
    }

    private func scheduleReport() {
        reportTimer = clock.schedule(after: Channel.reportIntervalSeconds) { [weak self] in
            guard let self, self.isLive else { return }
            self.report()
            self.scheduleReport()
        }
    }

    private func pingNow() {
        let nonce = UUID().uuidString
        pingNonce = nonce
        pingSentNanos = clock.uptimeNanos
        transport.frame(bindingId, ChannelFrames.ping(nonce: nonce))
        pingTimer?.cancel()
        pingTimer = clock.schedule(after: Channel.pingIntervalSeconds) { [weak self] in
            guard let self, self.isLive else { return }
            self.pingNow()
        }
    }

    private func takePong(_ nonce: String) {
        guard !nonce.isEmpty, nonce == pingNonce else { return }
        pingNonce = ""
        view.rttMs = Int((Double(clock.uptimeNanos &- pingSentNanos) / 1e6).rounded())
    }

    private func takeState(_ state: ChannelClientState) {
        stateHash = state.hash
        serverPaths = state.serverPaths
        let isNewUrls = !state.urls.isEmpty && Set(state.urls) != Set(view.binding.gatewayUrls)
        note { binding in
            if !state.urls.isEmpty { binding.gatewayUrls = state.urls }
            binding.overlays = state.overlays
        }
        endRefresh()
        view.connection = state.isDisabled ? .waiting : .connected
        view.waitReason = state.isDisabled ? .disabled : nil
        view.waitRefusal = nil
        view.services = state.services
        view.apps = state.apps
        view.terminals = state.terminals
        view.reachedThrough = state.reachedThrough
        view.isPanelAllowed = state.isPanelAllowed
        if isNewUrls { networkChanged() }
    }

    @discardableResult
    private func report(isRefresh: Bool = false) -> Bool {
        transport.frame(bindingId, ChannelFrames.report(stateHash: stateHash, machine: machine, isRefresh: isRefresh))
    }

    private func note(_ change: (inout HubBinding) -> Void) {
        guard let kept = try? store.update(bindingId, change) else { return }
        view.binding = kept
    }

    private func endRefresh() {
        refreshTimer?.cancel()
        refreshTimer = nil
        view.jobs.isRefreshing = false
    }

    /// Every address of a round failed: `no_network` with no countdown while the phone has none, else `hub_silent`
    /// until the next round, at the seconds the transport names or the backoff, which then doubles.
    private func silent(_ refusal: ClientError, nextRound: Double?) -> Double {
        if !hasNetwork() {
            hold(.noNetwork, refusal)
            return Channel.connectTimeoutSeconds
        }
        let wait: Double
        if let nextRound {
            wait = nextRound
        } else {
            wait = backoff
            backoff = min(backoff * 2, Channel.backoffMaxSeconds)
        }
        return waitFor(HubWaitReason.hubSilent, refusal, wait)
    }

    private func waitFor(_ reason: HubWaitReason, _ refusal: ClientError?, _ seconds: Double) -> Double {
        endRefresh()
        logWait(reason, refusal, seconds)
        let nextAt = seconds > 0 ? clock.now + seconds : 0
        view = waiting(view, reason, refusal, nextRoundAt: nextAt)
        countdown?.cancel()
        countdown = nil
        if seconds > 0 {
            countdown = clock.schedule(after: seconds) { [weak self] in
                guard let self else { return }
                self.countdown = nil
                if self.view.nextRoundAt == nextAt && !self.isLive { self.view = self.dialling(self.view) }
            }
        }
        return seconds
    }

    private func hold(_ reason: HubWaitReason, _ refusal: ClientError?) {
        held = reason
        endRefresh()
        countdown?.cancel()
        countdown = nil
        log("waiting on \(reason.rawValue): \(refusal?.code ?? "")")
        view = waiting(view, reason, refusal, nextRoundAt: 0)
    }

    /// Log a wait. A wait after `control_unavailable` writes its line at the first refusal, then at most once every
    /// `Channel.refusalLogIntervalSeconds` with the count since the line before.
    private func logWait(_ reason: HubWaitReason, _ refusal: ClientError?, _ seconds: Double) {
        let line = "waiting on \(reason.rawValue) for \(Int(seconds))s: \(refusal?.code ?? "")"
        guard refusal?.code == Channel.codeControlUnavailable else {
            log(line)
            return
        }
        unavailableCount += 1
        let now = clock.now
        let loggedAt = unavailableLoggedAt
        if let loggedAt, now - loggedAt < Channel.refusalLogIntervalSeconds { return }
        let count = unavailableCount
        unavailableCount = 0
        unavailableLoggedAt = now
        log(loggedAt == nil ? line : "\(line), \(count) times since the last line")
    }

    private func log(_ text: String) {
        writeLog("hub \(view.binding.title): \(text)")
    }

    private func dialling(_ view: HubView) -> HubView {
        var next = view
        next.connection = .connecting
        next.waitReason = nil
        next.waitRefusal = nil
        next.nextRoundAt = 0
        return next
    }

    private func waiting(_ view: HubView, _ reason: HubWaitReason, _ refusal: ClientError?, nextRoundAt: Double)
        -> HubView
    {
        var next = view
        next.connection = .waiting
        next.waitReason = reason
        next.waitRefusal = refusal
        next.nextRoundAt = nextRoundAt
        return next
    }
}
