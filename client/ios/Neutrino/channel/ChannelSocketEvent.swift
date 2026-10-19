import Foundation

/// What happens on a socket, in the order it happens.
enum ChannelSocketEvent {
    /// The upgrade finished: the pin checked out and frames may be sent.
    case opened
    /// A text frame arrived.
    case text(String)
    /// A binary frame arrived: the stream id, then the bytes.
    case binary(Data)
    /// The hub closed the socket with this close code.
    case closed(code: Int)
    /// The socket failed: it did not open, the pin did not match, or the wire broke. The refusal is
    /// `hub_untrusted` for a certificate that is not the pinned one, else `hub_unreachable`; `isPortClosed`
    /// says the connect was refused, the host being up and the port not open.
    case failed(ClientError, isPortClosed: Bool)
}
