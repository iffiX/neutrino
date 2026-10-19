import Foundation

/// The entry a local port dialog configures.
struct LocalPortTarget: Identifiable {
    /// The hub.
    let bindingId: String

    /// The entry.
    let entryId: String

    /// The entry's title, the dialog's title.
    let title: String

    /// `<binding>/<entry>`.
    var id: String { "\(bindingId)/\(entryId)" }
}
