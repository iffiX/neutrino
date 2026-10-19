import Foundation

/// Where one hub's socket stands: the three kinds of a hub row's state line.
enum HubConnection: String {
    /// A round over the hub's addresses is dialling.
    case connecting
    /// The hub welcomed this phone and the socket is open.
    case connected
    /// No round is dialling; the view's wait reason names what the row waits for.
    case waiting
}
