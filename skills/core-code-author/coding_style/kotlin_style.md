# Kotlin style

The Android app (`client/android/`) is a Gradle project in Kotlin with Jetpack
Compose. This file is its language surface. The shared intent is set by
[naming_style.md](naming_style.md), [comment_style.md](comment_style.md) and
[exception_style.md](exception_style.md), and applies here as it does to
Python.

## Example

```kotlin
// BAD: file named after nothing, a noun bool, a force unwrap, a refusal thrown
// Utils.kt
class Manager(private val socket: WebSocket?) {
    var connected = false
    fun join(link: String) {
        socket!!.send(link)
        if (reply.code != null) throw Exception(reply.code)
    }
}

// GOOD: file named after its one type, is_ bool, null handled, refusal as a value
// ChannelSocketClient.kt
class ChannelSocketClient(private val socket: WebSocket) {
    var isConnected: Boolean = false
        private set

    fun join(link: EnrollmentLink): ChannelResult<Binding> {
        val reply = socket.request(link.toFrame())
        return reply.refusal?.let { ChannelResult.Refused(it.code, it.params) }
            ?: ChannelResult.Ok(reply.binding)
    }
}
```

## Formatting and linting

- ktlint is the formatter; `ktlint` must pass on every change, the same gate
  as black on Python.
- Android lint must pass under `./gradlew lint` with no warnings. Do not
  suppress a check with an annotation to silence a real problem.

## Files and directories

- A file holds one top-level type and is named after it in PascalCase, as
  Kotlin does: `ChannelSocketClient.kt`. A file of top-level functions is
  named after their one concept: `LinkParsing.kt`.
- Directories use `under_score`, like the rest of the repository
  ([layout_style.md](layout_style.md)). A package segment is the directory
  name: `io.github.iffix.neutrino.overlay_driver`.
- No grab-bag files or directories: no `Utils.kt`, no `common/`.
- Non-configurable constants live in one `Constants.kt` per Gradle module,
  as `const val` in capitals with the domain prefix: `CHANNEL_PING_SECONDS`.

## Naming

- Types are PascalCase; functions, properties and locals are camelCase.
- Booleans read as questions: `isConnected`, `hasPassword`. A property decoded
  from a wire field is the camelCase form of that field (`is_token_required`
  becomes `isTokenRequired`), mapped once with `@SerialName`.
- Classes follow the `<Domain><Thing><Role>` families of
  [../design/class_hierarchy.md](../design/class_hierarchy.md). An Android
  base class names the role: `OverlayVpnService`, `FilesDocumentsProvider`.

## Comments

- English only, stating the fact, with no narrated reasoning
  ([comment_style.md](comment_style.md)).
- Every public declaration has a KDoc comment: what it is, one `@param` per
  parameter, `@return`, and one `@throws` per kind thrown on purpose, the
  same contract as Python's `Args:`, `Returns:` and `Raises:`.

## Errors

- Kotlin's and Java's own exceptions first: `IllegalArgumentException` for a
  wrong argument, `IllegalStateException` for a call in the wrong state,
  `IOException` and its subclasses for a file, a socket or the network.
- Kinds of the module's own are declared in one `Exceptions.kt` per Gradle
  module and nowhere else, each named after what happened.
- A refusal from the hub is a value, never a throw. A call that the hub can
  refuse returns a sealed result whose refused case carries `code` and
  `params`, the `{code, params}` shape of
  [../design/protocol.md](../design/protocol.md).

## Null safety

- No `!!` outside tests. Narrow with `?.`, `?:`, `let`, or a smart cast after
  a check, and return or throw the named kind when the value is missing.
- No `lateinit` on a value the constructor could take.

## File internal order

Top-level constants, then top-level functions, then the type. Inside a class:
properties, `init`, public functions, private functions, and the companion
object last. A composable file holds one screen or one component, with its
private previews at the end.

## Tests

- JUnit, run by `./gradlew test`. A source file
  `src/main/kotlin/<package path>/<Type>.kt` is tested by
  `src/test/kotlin/<package path>/<Type>Test.kt`; the mirror rule of
  [../design/tests.md](../design/tests.md) applies unchanged.
- The channel's frames are checked against
  `hub/tests/web/channel_schema.json`, the golden the hub's own tests pin.
