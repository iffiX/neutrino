import Foundation

/// A page the in-app browser shows: a forward's loopback address and the title its top bar reads.
struct BrowserTarget: Equatable, Identifiable {
    /// The hub the page is forwarded from.
    let bindingId: String

    /// The loopback address, with the token where the page takes one.
    let url: String

    /// The entry's title, or the hub's name for its panel.
    let title: String

    /// The address, as the page keys it.
    var id: String { url }
}
