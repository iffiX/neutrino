import Foundation

/// The names an upload, a new folder and a rename take in a share's folder.
enum ShareName {
    /// The name one attempt tries, as the system's own Files names a copy: the name itself at attempt 0, then
    /// `<name> (<n>).<ext>` for a file, the number before the extension, and `<name> (<n>)` for a folder or a
    /// file whose only dot starts its name.
    ///
    /// - Parameters:
    ///   - name: The name asked for.
    ///   - isFolder: Whether a folder is named.
    ///   - attempt: The attempt, from 0.
    /// - Returns: The name to try.
    static func numbered(_ name: String, isFolder: Bool, attempt: Int) -> String {
        guard attempt > 0 else { return name }
        guard !isFolder, let dot = name.lastIndex(of: "."), dot != name.startIndex else {
            return "\(name) (\(attempt))"
        }
        return "\(name[..<dot]) (\(attempt))\(name[dot...])"
    }

    /// Whether a typed name can name a file or a folder in a share: not empty, not `.` or `..`, and none of the
    /// characters a share forbids.
    ///
    /// - Parameter name: The name.
    /// - Returns: True when it can.
    static func isValid(_ name: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed == name, name != ".", name != ".." else { return false }
        return !name.unicodeScalars.contains { scalar in
            scalar.value < 0x20 || SharePage.nameForbidden.unicodeScalars.contains(scalar)
        }
    }
}
