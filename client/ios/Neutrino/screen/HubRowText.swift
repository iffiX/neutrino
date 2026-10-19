import Foundation

/// What a hub row says: its dot, its state line and its tags, by the client page's tables.
enum HubRowText {
    /// The waiting reasons a person has to act on, drawn with a red dot.
    static let personReasons: Set<HubWaitReason> = [.untrusted, .unknownDevice, .tooOld, .joinRefused]

    /// The status dot of a hub row.
    ///
    /// - Parameter hub: The hub.
    /// - Returns: The tone.
    static func tone(_ hub: HubView) -> DotTone {
        if hub.jobs.isAnyRunning || hub.connection == .connecting { return .pulse }
        if hub.connection == .connected { return .ok }
        if let reason = hub.waitReason, personReasons.contains(reason) { return .bad }
        if !hub.hasConnected && !hub.isDisabled { return .off }
        return .wait
    }

    /// The whole seconds left before a waiting hub's next round, rounded up.
    ///
    /// - Parameters:
    ///   - hub: The hub.
    ///   - now: The wall time now.
    /// - Returns: The seconds, 0 once the moment has come, or nil while no countdown runs.
    static func secondsToNextRound(_ hub: HubView, now: Double) -> Int? {
        guard hub.connection == .waiting, hub.nextRoundAt > 0 else { return nil }
        return Int(max(hub.nextRoundAt - now, 0).rounded(.up))
    }

    /// The state word's key: the running job's word, else the connection's, else the reason it waits for; a
    /// countdown that reached 0 reads as connecting.
    ///
    /// - Parameters:
    ///   - hub: The hub.
    ///   - now: The wall time now.
    /// - Returns: The catalog key.
    static func stateKey(_ hub: HubView, now: Double) -> String {
        if hub.jobs.isLeaving { return "ui.job.leaving" }
        if hub.jobs.isRefreshing { return "ui.job.refreshing" }
        if hub.isConnected && Channel.reachedThrough.contains(hub.reachedThrough) {
            return "ui.state.connected_through"
        }
        guard hub.connection == .waiting, let reason = hub.waitReason else {
            return "ui.state.\(hub.connection.rawValue)"
        }
        if secondsToNextRound(hub, now: now) == 0 { return "ui.state.connecting" }
        return "ui.state.\(reason.rawValue)"
    }

    /// The state word, worded: `Connected · <way>` names the way the socket reached the hub.
    ///
    /// - Parameters:
    ///   - hub: The hub.
    ///   - words: The catalog.
    ///   - now: The wall time now.
    /// - Returns: The sentence.
    static func stateWord(_ hub: HubView, words: WordCatalog, now: Double) -> String {
        words.word(stateKey(hub, now: now), ["way": words.word("ui.through.\(hub.reachedThrough)")])
    }

    /// The state line: the state word, then ` · ` and what ends the wait when the row waits for one: the seconds
    /// left, the refusal's wording, the update a client too old for the hub needs, or the Reconnect button's name.
    ///
    /// - Parameters:
    ///   - hub: The hub.
    ///   - words: The catalog.
    ///   - now: The wall time now.
    /// - Returns: The sentence.
    static func stateLine(_ hub: HubView, words: WordCatalog, now: Double) -> String {
        let word = stateWord(hub, words: words, now: now)
        guard let reason = hub.waitReason, stateKey(hub, now: now) == "ui.state.\(reason.rawValue)" else { return word }
        var action: String?
        if let seconds = secondsToNextRound(hub, now: now) {
            action = words.word("ui.action.retry_in", ["s": "\(seconds)"])
        } else if reason == .joinRefused, let refusal = hub.waitRefusal {
            action = words.refusal(refusal)
        } else if reason == .tooOld, hub.waitRefusal?.code == Channel.codeProtocolTooOld {
            action = words.word("ui.action.update_client")
        } else if reason == .replaced {
            action = words.word("ui.reconnect")
        }
        return [word, action].compactMap { $0 }.joined(separator: " · ")
    }

    /// The tags of a connected hub row with no job running: the state word with the way the socket reached the
    /// hub, then the last round trip once a pong measured it.
    ///
    /// - Parameters:
    ///   - hub: The hub.
    ///   - words: The catalog.
    /// - Returns: The tags, empty unless the row is connected and idle.
    static func tags(_ hub: HubView, words: WordCatalog) -> [String] {
        guard hub.isConnected, !hub.jobs.isLeaving, !hub.jobs.isRefreshing else { return [] }
        let rtt = hub.rttMs.map { words.word("ui.state.rtt", ["ms": "\($0)"]) }
        return [stateWord(hub, words: words, now: 0), rtt].compactMap { $0 }
    }
}
