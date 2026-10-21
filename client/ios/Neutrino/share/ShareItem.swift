import Foundation

/// One file or folder of a share's folder.
struct ShareItem: Equatable, Identifiable {
    /// Its name in the folder.
    let name: String

    /// Whether it is a folder.
    let isFolder: Bool

    /// Its size in bytes; 0 for a folder.
    let size: Int64

    /// When its content last changed, nil when the share names no time.
    let modified: Date?

    /// The name, as a list keys the row.
    var id: String { name }

    /// A folder's items in the order the page lists them: folders first, then files, each by name as the Files
    /// app sorts names, numbers by their value.
    ///
    /// - Parameter items: The items, in any order.
    /// - Returns: The items, ordered.
    static func ordered(_ items: [ShareItem]) -> [ShareItem] {
        items.sorted { left, right in
            if left.isFolder != right.isFolder { return left.isFolder }
            switch left.name.localizedStandardCompare(right.name) {
            case .orderedAscending: return true
            case .orderedDescending: return false
            case .orderedSame: return left.name < right.name
            }
        }
    }
}
