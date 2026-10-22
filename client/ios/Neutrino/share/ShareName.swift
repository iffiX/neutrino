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

    /// The name an item from Photos uploads under: the name Photos suggests with the extension of the file the
    /// picker handed over, or that file's own name when Photos suggests none. A suggested name that already ends
    /// in that extension takes it once.
    ///
    /// - Parameters:
    ///   - suggested: The name Photos suggests, nil for none.
    ///   - received: The file the picker handed over.
    /// - Returns: The name.
    static func photo(suggested: String?, received: URL) -> String {
        guard let suggested, !suggested.isEmpty else { return received.lastPathComponent }
        let ext = received.pathExtension
        guard !ext.isEmpty, !suggested.lowercased().hasSuffix("." + ext.lowercased()) else { return suggested }
        return suggested + "." + ext
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
