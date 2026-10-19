import Foundation

/// How a hello on a round's socket ended.
enum HubHandshake {
    /// The hub welcomed this phone.
    case welcomed(ChannelWelcome)
    /// The hub refused the hello with a code the binding survives or not.
    case rejected(ClientError)
    /// The socket failed or the hub answered no welcome in time.
    case failed(ClientError)
}
