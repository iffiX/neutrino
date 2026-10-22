import Foundation

/// The share page as it draws: the share, the folder shown, its items, and every job and code on the page.
struct ShareView: Equatable {
    /// The share.
    let target: ShareTarget

    /// The folder shown.
    var path = SharePath()

    /// The folder's items, in the page's order.
    var items: [ShareItem] = []

    /// Whether the share is logged in, which the page's actions and the rows' menus need.
    var isConnected = false

    /// Whether the folder is being read.
    var isListing = false

    /// Whether a new folder is being made.
    var isMakingFolder = false

    /// The code of the last failed listing, new folder, item from Photos or login, until a refresh, a change of
    /// folder, a new folder or the next login.
    var error: ClientError?

    /// Every transfer that runs or ended in a code, by its path in the share.
    var transfers: [String: ShareTransfer] = [:]

    /// The rename or delete running on an item, by its path in the share.
    var jobs: [String: ShareItemJob] = [:]

    /// The code of an item's last rename or delete, by its path, until its next press or a refresh.
    var errors: [String: ClientError] = [:]

    /// The local file the preview shows, nil for none.
    var preview: URL?

    /// The local file the export picker saves, nil for none.
    var export: URL?

    /// The uploads into the folder shown, by name.
    var uploads: [ShareTransfer] {
        transfers.values.filter { $0.kind == .upload && $0.path.parent == path }.sorted {
            $0.path.name < $1.path.name
        }
    }

    /// The folder's items no upload is writing.
    var listed: [ShareItem] {
        items.filter { transfers[path.child($0.name).text]?.kind != .upload }
    }
}
