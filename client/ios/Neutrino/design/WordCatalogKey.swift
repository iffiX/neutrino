import SwiftUI

/// The sentences a view words itself with, set once at the root by the language the person chose.
struct WordCatalogKey: EnvironmentKey {
    static let defaultValue = WordCatalog(words: [:])
}
