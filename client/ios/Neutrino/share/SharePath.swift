import Foundation

/// A place in a share: the names from the share's root down to a folder or a file, empty for the root.
struct SharePath: Equatable, Hashable {
    /// The names, from the root down.
    let parts: [String]

    /// A place in a share.
    ///
    /// - Parameter parts: The names, from the root down.
    init(_ parts: [String] = []) {
        self.parts = parts
    }

    /// The path the SMB client takes: the names joined by `/`, empty for the root.
    var text: String { parts.joined(separator: "/") }

    /// The last name, empty for the root.
    var name: String { parts.last ?? "" }

    /// The folder that holds it, nil for the root.
    var parent: SharePath? { parts.isEmpty ? nil : SharePath(Array(parts.dropLast())) }

    /// A place inside this folder.
    ///
    /// - Parameter name: The name in the folder.
    /// - Returns: The place.
    func child(_ name: String) -> SharePath {
        SharePath(parts + [name])
    }
}
