import Foundation

/// Bytes a stream sends as the hub's credit allows, and how far they are sent.
struct ChannelStreamSend {
    /// The bytes.
    let data: Data

    /// Called with true once every byte is sent, false when the send is dropped.
    let completion: ((Bool) -> Void)?

    /// How many bytes are sent.
    var offset = 0
}
