import Foundation

/// Every sentence a page shows in one language, by the dotted key the desktop client uses. The desktop
/// client's catalog is read first and the app's own on top of it; a key with no sentence reads as the key.
struct WordCatalog {
    /// The sentences by key, `{name}` marking where a parameter goes.
    let words: [String: String]

    /// The sentence for one key, its parameters filled in.
    ///
    /// - Parameters:
    ///   - key: The dotted key, such as `ui.add_hub`.
    ///   - params: The values its `{name}` markers take; a marker with no value stays as it is.
    /// - Returns: The sentence, or the key when the catalog has none.
    func word(_ key: String, _ params: [String: String] = [:]) -> String {
        guard var sentence = words[key] else { return key }
        for (name, value) in params {
            sentence = sentence.replacingOccurrences(of: "{\(name)}", with: value)
        }
        return sentence
    }

    /// The sentence for a refusal, or its code when no sentence names it.
    ///
    /// - Parameter refusal: The refusal.
    /// - Returns: The worded refusal.
    func refusal(_ refusal: ClientError) -> String {
        let key = "code.\(refusal.code)"
        return words[key] == nil ? refusal.code : word(key, refusal.wordParams)
    }

    /// Whether the catalog holds a sentence for one key.
    ///
    /// - Parameter key: The dotted key.
    /// - Returns: True when the key has a sentence.
    func has(_ key: String) -> Bool {
        words[key] != nil
    }

    /// One catalog file as dotted keys.
    ///
    /// - Parameter data: The file's JSON: nested objects of strings.
    /// - Returns: Every string under its dotted path; empty when the data is not a JSON object.
    static func flatten(_ data: Data) -> [String: String] {
        guard let root = (try? JSONValue.parse(data))?.objectValue else { return [:] }
        var flat: [String: String] = [:]
        collect("", root, into: &flat)
        return flat
    }

    /// The catalog of one language from a bundle.
    ///
    /// - Parameters:
    ///   - language: One of the client's languages.
    ///   - bundle: The bundle the catalogs are in.
    /// - Returns: The desktop client's sentences with the app's own on top.
    static func load(language: String, bundle: Bundle = .main) -> WordCatalog {
        var words: [String: String] = [:]
        for directory in [Client.desktopLocalesDirectory, Client.appLocalesDirectory] {
            guard let url = bundle.url(forResource: language, withExtension: "json", subdirectory: directory),
                let data = try? Data(contentsOf: url)
            else { continue }
            words.merge(flatten(data)) { _, app in app }
        }
        return WordCatalog(words: words)
    }

    private static func collect(_ prefix: String, _ node: [String: JSONValue], into flat: inout [String: String]) {
        for (name, value) in node {
            let key = prefix.isEmpty ? name : "\(prefix).\(name)"
            switch value {
            case .object(let child): collect(key, child, into: &flat)
            case .string(let text): flat[key] = text
            default: break
            }
        }
    }
}
