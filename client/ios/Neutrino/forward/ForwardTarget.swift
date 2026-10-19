import Foundation

/// What a forward's streams name: its hub, and the arguments of each `connect` stream.
struct ForwardTarget {
    /// The hub.
    let bindingId: String

    /// `{id}` for an entry, `{is_panel: true}` for the panel.
    let args: [String: JSONValue]
}
