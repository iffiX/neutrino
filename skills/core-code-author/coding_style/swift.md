# Swift style

The iOS app (`client/ios/`) is written in Swift with SwiftUI, in three
targets: the app, its unit tests and its UI tests. This file is its language surface. The
shared intent is set by [naming.md](naming.md),
[comment.md](comment.md) and
[exception.md](exception.md), and applies here as it does to
Python.

## Example

```swift
// BAD: file named after nothing, a noun bool, a force unwrap, a refusal as a string
// Helpers.swift
final class Manager {
    var connected = false
    func join(_ link: String) throws {
        let reply = try socket!.request(link)
        if reply.code != nil { throw NSError(domain: reply.code!, code: 0) }
    }
}

// GOOD: file named after its one type, is_ bool, optional narrowed, one Error enum
// ChannelSocketClient.swift
final class ChannelSocketClient {
    private(set) var isConnected = false

    func join(_ link: EnrollmentLink) async throws -> Binding {
        let reply = try await socket.request(link.frame)
        if let refusal = reply.refusal {
            throw ChannelError.refused(code: refusal.code, params: refusal.params)
        }
        return reply.binding
    }
}
```

## Formatting and linting

- swift-format is the formatter; `swift-format lint --strict --recursive`
  must pass on every change, the same gate as black on Python.
- The build must finish with no warnings. Do not silence one with a pragma
  or an unused binding to hide a real problem.

## Project and dependencies

- `client/ios/project.yml`, the XcodeGen spec, is the project. The
  `.xcodeproj` is generated from it by `xcodegen generate` and never
  committed, so a target, a setting or a dependency changes in
  `project.yml` alone.
- A dependency is a Swift package declared in `project.yml` at an exact
  version. The dependencies are SwiftTerm 1.19.0, the MIT-licensed terminal
  view, and AMSMB2 4.0.3, the SMB client of the share page, which builds the
  LGPL-2.1 libsmb2 from its source into a framework of its own.
- The one dependency that is not a Swift package is the RustDesk core, the
  static library `packaging/build/build_core_rustdesk_ios.py` builds into
  `client/ios/cores/rustdesk/`. Swift reaches it only through the module map
  in `client/ios/rustdesk_core/`, and every call into it is under
  `#if NEUTRINO_RUSTDESK`, which only a device build that links the library
  sets.
- The version and the edition reach the build as `xcodebuild` build
  settings from `packaging/build/build_client_ios.py`, and are never
  written into `project.yml`.

## Files and directories

- A file holds one top-level type and is named after it in PascalCase, as
  Swift does: `ChannelSocketClient.swift`. A file holding one extension is
  `<Type>+<Concept>.swift`: `ChannelSocketClient+Frames.swift`.
- Directories use `under_score`, like the rest of the repository
  ([layout.md](layout.md)), except the target and bundle
  directories Xcode names after the target.
- No grab-bag files or groups: no `Helpers.swift`, no `Common/`.
- Non-configurable constants live in one `Constants.swift` per target or
  Swift package, as `static let` members of a caseless `enum` named after the
  domain: `Channel.pingSeconds`.

## Naming

- Types and protocols are PascalCase; functions, properties, cases and locals
  are camelCase.
- Booleans read as questions: `isConnected`, `hasPassword`. A property decoded
  from a wire field is the camelCase form of that field (`is_token_required`
  becomes `isTokenRequired`), mapped once in its `CodingKeys`.
- Classes follow the `<Domain><Thing><Role>` families of
  [../design/class_hierarchy.md](../design/class_hierarchy.md). A type that
  fills a system role names the role: `TerminalViewRepresentable`,
  `BrowserNavigationDelegate`.

## Comments

- English only, stating the fact, with no narrated reasoning
  ([comment.md](comment.md)).
- Every public declaration has a `///` comment: what it is, `- Parameters:`
  with one entry per parameter, `- Returns:`, and `- Throws:` naming each case
  thrown on purpose, the same contract as Python's `Args:`, `Returns:` and
  `Raises:`.

## Errors

- The system's own errors first: `URLError` for the network, `CocoaError` for
  a file, `DecodingError` for a payload that does not parse.
- Each target or Swift package declares one `Error` enum of its own, in its
  `Errors.swift` and nowhere else. A case is named after what happened:
  `vaultLocked`, never `platformFailure`.
- A refusal from the hub is the case `refused(code:params:)`, carrying the
  `{code, params}` shape of [../design/protocol.md](../design/protocol.md);
  the view reads the code and never parses a message.

## Optionals

- No force unwrap (`!`), no `try!`, and no implicitly unwrapped optional
  outside tests. Narrow with `guard let`, `if let` or `??`, and throw the
  named case when the value is missing.

## File internal order

Top-level constants, then free functions, then the type. Inside a type:
stored properties, `init`, public methods, private methods. Each protocol
conformance follows the type in its own `extension`, in the same file. A view
file holds one screen or one component, with its preview at the end.

## Tests

- XCTest, run by `xcodebuild test` on the iOS Simulator. A source file
  `Neutrino/<dir>/<Type>.swift` is tested by
  `NeutrinoTests/<dir>/<Type>Tests.swift`; the mirror rule of
  [../design/tests.md](../design/tests.md) applies unchanged.
- The channel's frames are checked against
  `hub/tests/web/channel_schema.json`, the golden the hub's own tests pin.
