import Foundation

/// The one socket to one hub: a connection round over the hub's addresses, the handshake, the state taken and
/// the reports sent, and the rounds again with the desktop client's backoff. Every call runs on the main queue.
///
/// A round dials at once the hub's address on each of its virtual networks, the address the hub's name resolves
/// to, and the binding's addresses. The view is `connecting` while a round dials, `connected` while the socket
/// is open, and `waiting` with a `HubWaitReason` otherwise, with the moment of the next round when one is due.
/// Every address failing waits 5 s, doubled up to 60 s, as `hub_silent`, or as `no_network` with no next round
/// while the phone has no network; `hub_untrusted` waits 60 s; `binding_unknown`, a protocol refusal and a
/// socket another replaced wait for a person. A socket that closes runs the next round at once. The open socket
/// sends a `ping` frame every 20 s and once after a move, and the `pong` echoing its nonce sets `rttMs`.
///
/// A network change runs a round at once. On a hub with no open socket it ends the wait and the round still
/// dialling. On a connected hub that round runs beside the channel, and its winner takes the channel only when
/// its path ranks higher than the channel's, or ranks the same and opened faster.
///
/// A binding whose ticket is unspent spends it at the round's socket's address, and the hello follows on that
/// socket with the token it returned.
final class HubSession {
    /// The binding the session is for.
    let bindingId: String

    private let store: BindingStore
    private let transport: HubTransport
    private let machine: ClientMachine
    private let clock: ClientClock
    private let resolveHubName: (@escaping (String?) -> Void) -> Void
    private let localNetworks: () -> [ChannelLocalNetwork]
    private let hasNetwork: () -> Bool
    private let onJoined: (String, String) -> Void
    private let onWelcomed: (String, String) -> Void
    private var isRunning = false
    private var isSuspended = false
    private var held: HubWaitReason?
    private var backoff = Channel.backoffMinSeconds
    private var stateHash = ""
    private var serverPaths: [String: ChannelPath] = [:]
    private var round: HubRound?
    private var waitTimer: ClientTimer?
    private var refreshTimer: ClientTimer?
    private var greeting: HubGreeting?
    private var live: HubLiveSocket?
    private var beside: HubRound?
    private var moving: HubGreeting?
    private var isNewsQueued = false
    private var isChangeQueued = false

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
    ///   - transport: How the hub is reached.
    ///   - machine: What this phone says about itself.
    ///   - clock: The time and the timers.
    ///   - resolveHubName: Calls back with the IPv4 address `hub.neutrino.internal` resolves to here, or nil.
    ///   - localNetworks: The networks this phone holds an address in, read at each comparison of paths.
    ///   - hasNetwork: Whether the phone has a network at all, read when every address of a round failed.
    ///   - onJoined: Called with the binding's id and the hub's id for it once its ticket is spent.
    ///   - onWelcomed: Called with the binding's id and the hub id after each welcome that opens a channel, before
    ///     the binding takes that id and before the socket's first state is read.
    init(
        bindingId: String, store: BindingStore, transport: HubTransport, machine: ClientMachine, clock: ClientClock,
        resolveHubName: @escaping (@escaping (String?) -> Void) -> Void,
        localNetworks: @escaping () -> [ChannelLocalNetwork], hasNetwork: @escaping () -> Bool,
        onJoined: @escaping (String, String) -> Void, onWelcomed: @escaping (String, String) -> Void = { _, _ in }
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
        view = HubView(
            binding: store.get(bindingId) ?? HubBinding(id: bindingId, gatewayUrl: "", fingerprint: "", token: ""))
    }

    /// Run the rounds until `stop()`.
    func start() {
        guard !isRunning else { return }
        isRunning = true
        runRound()
    }

    /// End the rounds and close the socket.
    func stop() {
        isRunning = false
        quiet()
    }

    /// The app is about to be suspended: the socket closes and no round runs until `foreground()`.
    func suspend() {
        isSuspended = true
        quiet()
        if !isLeftWaiting { view = dialling(view) }
    }

    /// The app came back to the foreground: a hub with no open socket runs a round now, with no backoff.
    func foreground() {
        isSuspended = false
        if live == nil { networkChanged() }
    }

    /// Take the binding back from a socket that replaced this one, and connect now.
    func reconnect() {
        guard held == .replaced else { return }
        held = nil
        backoff = Channel.backoffMinSeconds
        view = dialling(view)
        runRound()
    }

    /// A network changed: the phone's connectivity changed, a VPN another app runs came or went, or the hub's
    /// state named other addresses. A hub that waits for a person, or for the hub's admission, runs nothing; a
    /// hub with no open socket ends its wait and the round still dialling and runs a round now with the backoff
    /// at its floor; a connected hub runs a round beside its channel.
    func networkChanged() {
        switch held {
        case nil: break
        case .noNetwork?: held = nil
        default: return
        }
        if view.waitReason == .disabled { return }
        if live != nil {
            besideChange()
            return
        }
        if view.waitReason == .admissionPaused { return }
        backoff = Channel.backoffMinSeconds
        restartNow()
    }

    /// A person pressed refresh: the hub is asked again. A connected hub gets a report with `is_refresh`; a hub
    /// with no open socket ends its wait and the round still dialling, and runs a round now. A replaced or
    /// disabled hub, or one that waits only for Leave, takes no refresh. The refresh ends on a state frame, a
    /// code, or after 10 s.
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
        if let live {
            if !report(live.socket, isRefresh: true) { liveEnded(live, code: nil) }
        } else {
            held = nil
            backoff = Channel.backoffMinSeconds
            restartNow()
        }
        return true
    }

    /// Open a stream on the live socket.
    ///
    /// - Parameters:
    ///   - kind: The kind.
    ///   - args: Its arguments.
    ///   - hasBytes: Whether it carries bytes.
    /// - Returns: The stream, or `hub_unreachable` while the hub is not connected.
    func openStream(kind: String, args: [String: JSONValue], hasBytes: Bool) -> Result<ChannelStream, ClientError> {
        guard let live, view.isConnected else {
            return .failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"]))
        }
        return live.registry.open(kind: kind, args: args, hasBytes: hasBytes)
    }

    /// What the hub hands this phone on a `service` stream: an entry's material for `{id}`, the panel's
    /// one-time `{token}` for `{is_panel: true}`.
    ///
    /// - Parameters:
    ///   - args: The stream's arguments.
    ///   - completion: Called with the close's params, or its refusal.
    func openService(
        args: [String: JSONValue], completion: @escaping (Result<[String: JSONValue], ClientError>) -> Void
    ) {
        switch openStream(kind: Channel.kindService, args: args, hasBytes: false) {
        case .failure(let refusal): completion(.failure(refusal))
        case .success(let stream): stream.whenClosed(timeout: Channel.streamTimeoutSeconds, completion)
        }
    }

    private var isLeftWaiting: Bool {
        guard let held else { return false }
        return held != .noNetwork
    }

    private func quiet() {
        waitTimer?.cancel()
        waitTimer = nil
        round?.cancel()
        round = nil
        beside?.cancel()
        beside = nil
        greeting?.abandon()
        greeting = nil
        moving?.abandon()
        moving = nil
        isNewsQueued = false
        isChangeQueued = false
        if let live {
            self.live = nil
            live.end()
            view.connectedAddress = ""
            view.rttMs = nil
        }
    }

    private func restartNow() {
        if greeting != nil {
            isNewsQueued = true
            return
        }
        round?.cancel()
        round = nil
        runRound()
    }

    private func runRound() {
        waitTimer?.cancel()
        waitTimer = nil
        guard isRunning, !isSuspended, held == nil, live == nil, greeting == nil, round == nil,
            let binding = store.get(bindingId)
        else { return }
        view = dialling(view)
        let round = HubRound(
            transport: transport, fingerprint: binding.fingerprint, clock: clock,
            onWin: { [weak self] dial in self?.roundWon(dial) },
            onLose: { [weak self] refusals in self?.roundLost(refusals) })
        self.round = round
        round.start(urls: binding.candidateUrls(nameUrl: ""))
        dialName(on: round, binding: binding)
    }

    private func dialName(on round: HubRound, binding: HubBinding) {
        guard !round.isOver, let first = binding.storedUrls.first else { return }
        round.expectName()
        resolveHubName { [weak round] address in
            round?.nameResolved(address.map { ChannelAddress.url(first, onHost: $0) } ?? "")
        }
    }

    private func roundLost(_ refusals: [(url: String, refusal: ClientError)]) {
        let nameUrl = round?.nameUrl ?? ""
        round = nil
        let stored = store.get(bindingId)?.storedUrls ?? []
        var untrusted: ClientError?
        var failure: ClientError?
        for (url, refusal) in refusals {
            if refusal.code != Channel.codeHubUntrusted {
                failure = refusal
            } else if url != nameUrl || stored.contains(url) {
                untrusted = refusal
            }
        }
        if let untrusted {
            onRejected(untrusted)
        } else {
            onUnreachable(failure ?? .refusal(Channel.codeHubUnreachable, ["detail": "no address"]))
        }
    }

    private func roundWon(_ dial: HubRoundDial) {
        round = nil
        guard let socket = dial.socket else {
            onUnreachable(.refusal(Channel.codeHubUnreachable, ["detail": "the socket is gone"]))
            return
        }
        let greeting = HubGreeting(dial: dial, socket: socket)
        self.greeting = greeting
        guard let binding = store.get(bindingId) else {
            greeting.abandon()
            self.greeting = nil
            return
        }
        if binding.isPending {
            spend(binding, on: greeting)
        } else {
            hello(binding, on: greeting)
        }
    }

    private func spend(_ binding: HubBinding, on greeting: HubGreeting) {
        let body = ChannelFrames.joinRequest(ticket: binding.ticket, machine: machine)
        transport.post(baseUrl: greeting.dial.url, path: Channel.joinPath, fingerprint: binding.fingerprint, body: body)
        {
            [weak self, weak greeting] result in
            guard let self, let greeting, self.greeting === greeting, !greeting.isDone else { return }
            switch result {
            case .failure(let refusal):
                self.greetingFailed(greeting)
                switch refusal.code {
                case Channel.codeHubUnreachable: self.onUnreachable(refusal)
                case Channel.codeHubUntrusted: self.onRejected(refusal)
                case Channel.codeAdmissionPaused: self.onAdmissionPaused(refusal)
                default: self.hold(.joinRefused, refusal)
                }
            case .success(let answer):
                let id = answer.text("id")
                let token = answer.text("token")
                guard !id.isEmpty, !token.isEmpty else {
                    self.greetingFailed(greeting)
                    self.hold(.joinRefused, .refusal("enroll_no_token"))
                    return
                }
                let kept = try? self.store.update(self.bindingId) { binding in
                    binding.hubBindingId = id
                    binding.token = token
                    binding.ticket = ""
                    binding.gatewayUrl = greeting.dial.url
                }
                guard let kept else {
                    self.greetingFailed(greeting)
                    self.onUnreachable(.refusal(Channel.codeClientInternal, ["error": "the binding could not be kept"]))
                    return
                }
                self.view.binding = kept
                self.onJoined(self.bindingId, id)
                self.hello(kept, on: greeting)
            }
        }
    }

    private func hello(_ binding: HubBinding, on greeting: HubGreeting) {
        greet(binding, on: greeting) { [weak self] outcome in
            guard let self, self.greeting === greeting else { return }
            self.greeting = nil
            switch outcome {
            case .welcomed(let welcome):
                self.onWelcomed(self.bindingId, welcome.id)
                self.serve(greeting, welcome: welcome)
            case .rejected(let refusal):
                greeting.abandon()
                self.onRejected(refusal)
            case .failed(let refusal):
                greeting.abandon()
                self.onUnreachable(refusal)
            }
        }
    }

    private func greet(_ binding: HubBinding, on greeting: HubGreeting, completion: @escaping (HubHandshake) -> Void) {
        let finish: (HubHandshake) -> Void = { [weak greeting] outcome in
            guard let greeting, !greeting.isDone else { return }
            greeting.isDone = true
            greeting.timer?.cancel()
            greeting.timer = nil
            completion(outcome)
        }
        greeting.socket.onEvent = { [weak self] event in
            guard let self else { return }
            switch event {
            case .text(let text):
                switch ChannelInbound.decode(text) {
                case .refused(let refusal)?:
                    finish(.rejected(refusal))
                case .welcome(let welcome)? where welcome.role == Client.hubRole:
                    self.report(greeting.socket, isRefresh: self.view.jobs.isRefreshing)
                    finish(.welcomed(welcome))
                default:
                    finish(
                        .failed(
                            .refusal(Channel.codeHubUnreachable, ["detail": "the hub's first frame is not a welcome"])))
                }
            case .closed(let code):
                if code == Channel.closeRefused {
                    finish(.rejected(.refusal(Channel.codeHubRefused)))
                } else {
                    finish(
                        .failed(.refusal(Channel.codeHubUnreachable, ["detail": "the hub closed the socket (\(code))"]))
                    )
                }
            case .failed(let refusal, _):
                finish(.failed(refusal))
            case .opened, .binary:
                break
            }
        }
        greeting.timer = clock.schedule(after: Channel.connectTimeoutSeconds) {
            finish(.failed(.refusal(Channel.codeHubUnreachable, ["detail": "the hub did not answer in 10s"])))
        }
        greeting.socket.send(ChannelFrames.hello(binding: binding, machine: machine))
    }

    private func greetingFailed(_ greeting: HubGreeting) {
        greeting.abandon()
        if self.greeting === greeting { self.greeting = nil }
    }

    private func serve(_ greeting: HubGreeting, welcome: ChannelWelcome) {
        let live = HubLiveSocket(
            socket: greeting.socket, url: greeting.dial.url, openNanos: greeting.dial.openNanos, clock: clock)
        self.live = live
        backoff = Channel.backoffMinSeconds
        note { binding in
            binding.gatewayUrl = greeting.dial.url
            binding.hubId = welcome.id
            binding.hubName = welcome.name
        }
        view.connection = .connected
        view.waitReason = nil
        view.waitRefusal = nil
        view.nextRoundAt = 0
        view.software = welcome.software
        view.connectedAddress = greeting.dial.url
        view.hasConnected = true
        view.rttMs = nil
        live.socket.onEvent = { [weak self, weak live] event in
            guard let self, let live else { return }
            self.take(event, on: live)
        }
        scheduleReport(live)
        pingNow(live)
        if isNewsQueued {
            isNewsQueued = false
            besideChange()
        }
    }

    private func scheduleReport(_ live: HubLiveSocket) {
        live.reportTimer = clock.schedule(after: Channel.reportIntervalSeconds) { [weak self, weak live] in
            guard let self, let live, self.live === live else { return }
            self.report(live.socket)
            self.scheduleReport(live)
        }
    }

    private func pingNow(_ live: HubLiveSocket) {
        let nonce = UUID().uuidString
        live.pingNonce = nonce
        live.pingSentNanos = clock.uptimeNanos
        live.socket.send(ChannelFrames.ping(nonce: nonce))
        live.pingTimer?.cancel()
        live.pingTimer = clock.schedule(after: Channel.pingIntervalSeconds) { [weak self, weak live] in
            guard let self, let live, self.live === live else { return }
            let silence = Double(self.clock.uptimeNanos &- live.heardNanos) / 1e9
            if silence > Channel.silenceTimeoutSeconds {
                ClientLog.info("hub \(self.view.binding.title): the socket was silent for \(Int(silence))s")
                self.liveEnded(live, code: nil)
            } else {
                self.pingNow(live)
            }
        }
    }

    private func take(_ event: ChannelSocketEvent, on live: HubLiveSocket) {
        guard self.live === live else { return }
        live.heardNanos = clock.uptimeNanos
        switch event {
        case .text(let text):
            dispatch(text, on: live)
        case .binary(let data):
            live.registry.takeBinary(data)
        case .opened:
            break
        case .closed(let code):
            liveEnded(live, code: code)
        case .failed:
            liveEnded(live, code: nil)
        }
    }

    private func dispatch(_ text: String, on live: HubLiveSocket) {
        guard let frame = ChannelInbound.decode(text) else {
            ClientLog.info("hub \(view.binding.title): a frame the hub sent does not read")
            return
        }
        switch frame {
        case .state(let state):
            takeState(state)
            if self.live === live { report(live.socket) }
        case .close(let stream, let code, let params):
            live.registry.takeClose(stream: stream, code: code, params: params)
        case .credit(let stream, let bytes):
            live.registry.takeCredit(stream: stream, bytes: bytes)
        case .open(let stream, let kind):
            live.registry.refuse(stream: stream, kind: kind)
        case .pong(let nonce):
            takePong(nonce, on: live)
        case .refused(let refusal):
            endLive(live)
            onRejected(refusal)
        case .welcome, .unknown:
            break
        }
    }

    private func takePong(_ nonce: String, on live: HubLiveSocket) {
        guard !nonce.isEmpty, nonce == live.pingNonce else { return }
        live.pingNonce = ""
        view.rttMs = Int((Double(clock.uptimeNanos &- live.pingSentNanos) / 1e6).rounded())
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
        view.terminals = state.terminals
        view.reachedThrough = state.reachedThrough
        view.isPanelAllowed = state.isPanelAllowed
        if isNewUrls { networkChanged() }
    }

    private func liveEnded(_ live: HubLiveSocket, code: Int?) {
        guard self.live === live else { return }
        if moving != nil {
            live.isGone = true
            return
        }
        endLive(live)
        if code == Channel.closeReplaced {
            hold(.replaced, nil)
        } else if code == Channel.closeRefused {
            onRejected(.refusal(Channel.codeHubRefused))
        } else {
            runRound()
        }
    }

    private func endLive(_ live: HubLiveSocket) {
        if self.live === live { self.live = nil }
        live.end()
        beside?.cancel()
        beside = nil
        moving?.abandon()
        moving = nil
        isChangeQueued = false
        view = dialling(view)
        view.connectedAddress = ""
        view.rttMs = nil
    }

    private func besideChange() {
        guard let live, beside == nil, moving == nil else {
            isChangeQueued = true
            return
        }
        guard let binding = store.get(bindingId) else { return }
        let round = HubRound(
            transport: transport, fingerprint: binding.fingerprint, clock: clock,
            onWin: { [weak self] dial in self?.besideWon(dial, from: live) },
            onLose: { [weak self] _ in
                self?.beside = nil
                self?.besideEnded()
            })
        beside = round
        round.start(urls: binding.candidateUrls(nameUrl: ""))
        dialName(on: round, binding: binding)
    }

    private func besideWon(_ dial: HubRoundDial, from previous: HubLiveSocket) {
        beside = nil
        guard let socket = dial.socket else {
            besideEnded()
            return
        }
        guard live === previous, let binding = store.get(bindingId) else {
            socket.close(code: Channel.closeNormal)
            besideEnded()
            return
        }
        let path = pathOf(dial.url)
        let livePath = pathOf(previous.url)
        let isBetter = path.rank < livePath.rank || (path.rank == livePath.rank && dial.openNanos < previous.openNanos)
        guard isBetter else {
            socket.close(code: Channel.closeNormal)
            ClientLog.info(
                "hub \(view.binding.title): the channel stays on \(previous.url) (\(livePath.rawValue)); "
                    + "\(dial.url) (\(path.rawValue)) is no better")
            besideEnded()
            return
        }
        let greeting = HubGreeting(dial: dial, socket: socket)
        moving = greeting
        greet(binding, on: greeting) { [weak self] outcome in
            guard let self, self.moving === greeting else { return }
            self.moving = nil
            if case .welcomed(let welcome) = outcome, self.live === previous {
                self.moveTo(greeting, welcome: welcome, from: previous)
            } else {
                greeting.abandon()
                ClientLog.info("hub \(self.view.binding.title): the channel stays on \(previous.url)")
                if previous.isGone && self.live === previous {
                    self.endLive(previous)
                    self.runRound()
                    return
                }
            }
            self.besideEnded()
        }
    }

    private func besideEnded() {
        guard isChangeQueued, live != nil else { return }
        isChangeQueued = false
        besideChange()
    }

    private func moveTo(_ greeting: HubGreeting, welcome: ChannelWelcome, from previous: HubLiveSocket) {
        live = nil
        previous.end()
        ClientLog.info("hub \(view.binding.title): the channel moved from \(previous.url) to \(greeting.dial.url)")
        serve(greeting, welcome: welcome)
    }

    private func pathOf(_ url: String) -> ChannelPath {
        ChannelPath.of(
            url: url, overlays: store.get(bindingId)?.overlays ?? [], serverPaths: serverPaths,
            localNetworks: localNetworks())
    }

    @discardableResult
    private func report(_ socket: ChannelSocket, isRefresh: Bool = false) -> Bool {
        socket.send(ChannelFrames.report(stateHash: stateHash, machine: machine, isRefresh: isRefresh))
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

    private func onUnreachable(_ refusal: ClientError) {
        if !hasNetwork() {
            hold(.noNetwork, refusal)
            return
        }
        let wait = backoff
        backoff = min(backoff * 2, Channel.backoffMaxSeconds)
        waitFor(.hubSilent, refusal, wait)
    }

    private func onRejected(_ refusal: ClientError) {
        switch refusal.code {
        case Channel.codeHubUntrusted: waitFor(.untrusted, refusal, Channel.backoffMaxSeconds)
        case Channel.codeBindingUnknown: hold(.unknownDevice, refusal)
        case Channel.codeProtocolTooOld, Channel.codeProtocolTooNew: hold(.tooOld, refusal)
        default: waitFor(.hubSilent, refusal, Channel.backoffMaxSeconds)
        }
    }

    private func onAdmissionPaused(_ refusal: ClientError) {
        let retry = refusal.params["retry_after_s"]?.intValue.map(Double.init) ?? Channel.backoffMaxSeconds
        waitFor(.admissionPaused, refusal, max(retry, 1))
    }

    private func waitFor(_ reason: HubWaitReason, _ refusal: ClientError?, _ seconds: Double) {
        endRefresh()
        ClientLog.info(
            "hub \(view.binding.title): waiting on \(reason.rawValue) for \(Int(seconds))s: \(refusal?.code ?? "") "
                + "\(refusal?.wordParams ?? [:])")
        view = waiting(view, reason, refusal, nextRoundAt: clock.now + seconds)
        waitTimer?.cancel()
        let delay = isNewsQueued ? 0 : seconds
        isNewsQueued = false
        waitTimer = clock.schedule(after: delay) { [weak self] in
            self?.waitTimer = nil
            self?.runRound()
        }
    }

    private func hold(_ reason: HubWaitReason, _ refusal: ClientError?) {
        held = reason
        endRefresh()
        ClientLog.info("hub \(view.binding.title): waiting on \(reason.rawValue): \(refusal?.code ?? "")")
        view = waiting(view, reason, refusal, nextRoundAt: 0)
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
