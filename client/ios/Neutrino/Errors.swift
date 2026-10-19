import Foundation

/// What the app's own calls fail with.
enum ClientError: Error, Equatable {
    /// A refusal, from the hub or from this side, in the protocol's `{code, params}` shape.
    case refused(code: String, params: [String: JSONValue])
}

extension ClientError {
    /// The refusal's code, worded by the catalog's `code.<code>`.
    var code: String {
        switch self {
        case .refused(let code, _): return code
        }
    }

    /// The values a sentence about the refusal needs.
    var params: [String: JSONValue] {
        switch self {
        case .refused(_, let params): return params
        }
    }

    /// The parameters as the word catalog fills them in: strings, numbers and booleans as text.
    var wordParams: [String: String] {
        params.mapValues { $0.text }
    }

    /// A refusal with text parameters.
    ///
    /// - Parameters:
    ///   - code: The code.
    ///   - params: The parameters, each a text.
    /// - Returns: The refusal.
    static func refusal(_ code: String, _ params: [String: String] = [:]) -> ClientError {
        .refused(code: code, params: params.mapValues { JSONValue.string($0) })
    }
}
