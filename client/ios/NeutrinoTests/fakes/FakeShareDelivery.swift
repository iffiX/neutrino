import Foundation

@testable import Neutrino

/// An item a picker hands over at once: a file of some text under a name, or a failure.
struct FakeShareDelivery: ShareDelivery {
    /// The name the file is put under.
    let name: String

    /// The file's text; nil makes the delivery fail.
    let text: String?

    func deliver(into place: URL, completion: @escaping (Result<URL, Error>) -> Void) {
        guard let text else {
            completion(.failure(CocoaError(.fileReadUnknown)))
            return
        }
        let file = place.appendingPathComponent(name)
        completion(Result { try Data(text.utf8).write(to: file) }.map { file })
    }
}
