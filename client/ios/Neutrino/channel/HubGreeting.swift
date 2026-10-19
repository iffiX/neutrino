import Foundation

/// A round's winner on its way to carrying the channel: its ticket being spent, then its one hello.
final class HubGreeting {
    /// The winner.
    let dial: HubRoundDial

    /// The winner's socket.
    let socket: ChannelSocket

    /// The hello's wait for the welcome.
    var timer: ClientTimer?

    /// Whether the greeting ended, by a welcome, a refusal, a failure or a stop.
    var isDone = false

    /// Greet on a winner's socket.
    ///
    /// - Parameters:
    ///   - dial: The winner.
    ///   - socket: Its socket.
    init(dial: HubRoundDial, socket: ChannelSocket) {
        self.dial = dial
        self.socket = socket
    }

    /// End the greeting and close its socket.
    func abandon() {
        isDone = true
        timer?.cancel()
        timer = nil
        socket.onEvent = nil
        socket.close(code: Channel.closeNormal)
    }
}
