package io.github.iffix.neutrino.files

/**
 * One held connection per share root. A request that loses its connection closes only that
 * connection, and a request on a reused connection tries once more on a new one; a root is never
 * marked down, so the next request connects again. A connection idle for long, or held while the
 * app was away from the foreground, is probed once before its next request.
 *
 * @param C What one connection is.
 * @param open Connect to a root with a login.
 * @param probe Whether a held connection still answers.
 * @param close Close a connection.
 * @param isLost Whether a failure means the connection is gone, rather than a refusal.
 * @param idleProbeMillis How long a connection may sit unused before it is probed.
 * @param clock The time in milliseconds.
 */
class ShareConnectionPool<C>(
    private val open: (ShareRoot, ShareLogin) -> C,
    private val probe: (C) -> Boolean,
    private val close: (C) -> Unit,
    private val isLost: (Exception) -> Boolean,
    private val idleProbeMillis: Long,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val held = mutableMapOf<String, Held<C>>()

    /**
     * Run one request on a root's connection.
     *
     * @param root The share.
     * @param login Its login.
     * @param action The request.
     * @return What the request returned.
     * @throws Exception Whatever connecting or the request threw, after the one retry.
     */
    fun <T> call(root: ShareRoot, login: ShareLogin, action: (C) -> T): T {
        val reused = checked(root.key)
        val connection = reused ?: connect(root, login)
        try {
            return action(connection).also { touch(root.key) }
        } catch (error: Exception) {
            if (!isLost(error)) throw error
            discard(root.key, connection)
            if (reused == null) throw error
        }
        val fresh = connect(root, login)
        try {
            return action(fresh).also { touch(root.key) }
        } catch (error: Exception) {
            if (isLost(error)) discard(root.key, fresh)
            throw error
        }
    }

    /** The app came back to the foreground: every held connection is probed before its next request. */
    fun markStale() {
        synchronized(held) { for (entry in held.values) entry.isStale = true }
    }

    /**
     * Close a root's connection, as after its login changed.
     *
     * @param rootKey The share's root id.
     */
    fun drop(rootKey: String) {
        val gone = synchronized(held) { held.remove(rootKey) } ?: return
        close(gone.connection)
    }

    private fun checked(rootKey: String): C? {
        val entry = synchronized(held) { held[rootKey] } ?: return null
        val isDue = entry.isStale || clock() - entry.lastUsed >= idleProbeMillis
        if (!isDue) return entry.connection
        if (probe(entry.connection)) {
            entry.isStale = false
            entry.lastUsed = clock()
            return entry.connection
        }
        discard(rootKey, entry.connection)
        return null
    }

    private fun connect(root: ShareRoot, login: ShareLogin): C {
        val connection = open(root, login)
        val before = synchronized(held) { held.put(root.key, Held(connection, clock())) }
        if (before != null && before.connection !== connection) close(before.connection)
        return connection
    }

    private fun touch(rootKey: String) {
        synchronized(held) { held[rootKey]?.lastUsed = clock() }
    }

    private fun discard(rootKey: String, connection: C) {
        synchronized(held) { if (held[rootKey]?.connection === connection) held.remove(rootKey) }
        close(connection)
    }

    private class Held<C>(val connection: C, var lastUsed: Long, var isStale: Boolean = false)
}
