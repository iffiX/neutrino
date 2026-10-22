import Foundation
import UniformTypeIdentifiers

/// One item Upload from Photos picked: the file of its original, the first image or movie type the picker
/// offers, copied out of the picker's temporary place before the picker's callback returns, under the name
/// Photos suggests with that file's extension.
struct SharePhotoDelivery: ShareDelivery {
    /// The picker's provider of the item.
    let provider: NSItemProvider

    func deliver(into place: URL, completion: @escaping (Result<URL, Error>) -> Void) {
        let type = provider.registeredTypeIdentifiers.first { identifier in
            guard let type = UTType(identifier) else { return false }
            return type.conforms(to: .image) || type.conforms(to: .movie)
        }
        guard let type else {
            completion(.failure(CocoaError(.fileReadUnsupportedScheme)))
            return
        }
        let suggested = provider.suggestedName
        _ = provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
            guard let url else {
                completion(.failure(error ?? CocoaError(.fileReadUnknown)))
                return
            }
            completion(
                Result {
                    let kept = place.appendingPathComponent(ShareName.photo(suggested: suggested, received: url))
                    try FileManager.default.copyItem(at: url, to: kept)
                    return kept
                })
        }
    }
}
