import Foundation

/// One entry of a service page, with the hub that publishes it.
struct ServiceListItem: Identifiable {
    /// The hub.
    let hub: HubView

    /// The entry.
    let entry: ChannelServiceEntry

    /// `<binding>/<entry>`.
    var id: String { "\(hub.binding.id)/\(entry.id)" }
}
