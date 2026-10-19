import Foundation

/// The socket that carries one hub's channel, with its streams, its timers and its round trip probe.
final class HubLiveSocket {
    /// The socket.
    let socket: ChannelSocket

    /// The streams open on it.
    let registry: ChannelStreamRegistry

    /// The address it runs on.
    let url: String

    /// How long it took to open when it won its round, in nanoseconds.
    let openNanos: UInt64

    /// The nonce of the last ping sent on it, empty once its pong was taken.
    var pingNonce = ""

    /// When the last ping was sent, in the clock's nanoseconds.
    var pingSentNanos: UInt64 = 0

    /// When the hub last sent anything on it, in the clock's nanoseconds.
    var heardNanos: UInt64 = 0

    /// The next report.
    var reportTimer: ClientTimer?

    /// The next ping, and the look at its silence.
    var pingTimer: ClientTimer?

    /// Whether the hub closed it while a better socket was saying hello.
    var isGone = false

    /// Carry the channel on a round's winner.
    ///
    /// - Parameters:
    ///   - socket: The socket.
    ///   - url: Its address.
    ///   - openNanos: How long it took to open.
    ///   - clock: The timers its streams wait with.
    init(socket: ChannelSocket, url: String, openNanos: UInt64, clock: ClientClock) {
        self.socket = socket
        self.url = url
        self.openNanos = openNanos
        registry = ChannelStreamRegistry(socket: socket, clock: clock)
        heardNanos = clock.uptimeNanos
    }

    /// Stop the timers, end every stream and close the socket.
    func end() {
        reportTimer?.cancel()
        reportTimer = nil
        pingTimer?.cancel()
        pingTimer = nil
        socket.onEvent = nil
        registry.endAll()
        socket.close(code: Channel.closeNormal)
    }
}
