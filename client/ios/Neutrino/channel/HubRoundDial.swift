import Foundation

/// One address of a round: its socket, its timers and how its dialling went.
final class HubRoundDial {
    /// The address.
    let url: String

    /// The socket of the current attempt; nil between a refusal and the redial, and once settled.
    var socket: ChannelSocket?

    /// When the current attempt started, in the clock's nanoseconds.
    var attemptNanos: UInt64 = 0

    /// How long the winning attempt took to open, in nanoseconds; the largest value until it opens.
    var openNanos = UInt64.max

    /// The refusal of the last attempt the host refused, kept for when the address's connect time ends.
    var lastRefusal: ClientError?

    /// Whether the address failed for this round.
    var isSettled = false

    /// The end of the address's connect time.
    var deadline: ClientTimer?

    /// The next attempt after a refusal.
    var redial: ClientTimer?

    /// Dial one address of a round.
    ///
    /// - Parameter url: The address.
    init(url: String) {
        self.url = url
    }

    /// Stop both timers.
    func cancelTimers() {
        deadline?.cancel()
        deadline = nil
        redial?.cancel()
        redial = nil
    }
}
