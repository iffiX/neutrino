package io.github.iffix.neutrino.files

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ShareConnectionPoolTest {
    private val root =
        ShareRoot(key = "r1", title = "media", host = "10.0.0.5", share = "media", users = emptyList(), summary = "")
    private val login = ShareLogin("alice", "secret")
    private var now = 0L
    private var made = 0
    private val closed = mutableListOf<Int>()
    private val probed = mutableListOf<Int>()
    private val answering = mutableSetOf<Int>()
    private var isServerUp = true

    private val pool = ShareConnectionPool(
        open = { _, _ ->
            if (!isServerUp) throw IOException("no route to host")
            made += 1
            answering += made
            made
        },
        probe = { connection ->
            probed += connection
            connection in answering
        },
        close = { connection -> closed += connection },
        isLost = { it is IOException },
        idleProbeMillis = 30_000,
        clock = { now },
    )

    @Test
    fun aRootKeepsOneConnectionAcrossRequests() {
        assertEquals(1, pool.call(root, login) { it })
        assertEquals(1, pool.call(root, login) { it })
        assertEquals(1, made)
    }

    @Test
    fun aLostRequestOnAHeldConnectionClosesItAndTriesOnceOnANewOne() {
        pool.call(root, login) { it }
        var attempts = 0
        val answer = pool.call(root, login) { connection ->
            attempts += 1
            if (connection == 1) throw IOException("broken pipe")
            connection
        }
        assertEquals(2, answer)
        assertEquals(2, attempts)
        assertEquals(listOf(1), closed)
    }

    @Test
    fun aFailureLeavesTheRootUsableForTheNextRequest() {
        pool.call(root, login) { it }
        try {
            pool.call(root, login) { throw IOException("broken pipe") }
            fail("the second attempt failed too")
        } catch (_: IOException) {
            // Both attempts failed.
        }
        assertEquals(3, pool.call(root, login) { it })
    }

    @Test
    fun aRefusalClosesNothing() {
        pool.call(root, login) { it }
        try {
            pool.call(root, login) { throw IllegalStateException("access denied") }
            fail("the refusal was swallowed")
        } catch (_: IllegalStateException) {
            // The refusal comes back as it is.
        }
        assertTrue(closed.isEmpty())
        assertEquals(1, pool.call(root, login) { it })
    }

    @Test
    fun anUnreachableServerFailsAtOnceWithoutARetry() {
        isServerUp = false
        var attempts = 0
        try {
            pool.call(root, login) { attempts += 1 }
            fail("an unreachable server answered")
        } catch (_: IOException) {
            // The connect itself failed.
        }
        assertEquals(0, attempts)
    }

    @Test
    fun aHeldConnectionIsProbedOnceAfterTheAppComesBack() {
        pool.call(root, login) { it }
        pool.markStale()
        pool.call(root, login) { it }
        pool.call(root, login) { it }
        assertEquals(listOf(1), probed)
    }

    @Test
    fun aDeadConnectionFoundByTheProbeIsReplacedBeforeTheRequest() {
        pool.call(root, login) { it }
        answering.clear()
        pool.markStale()
        var seen = 0
        pool.call(root, login) { connection -> seen = connection }
        assertEquals(2, seen)
        assertEquals(listOf(1), closed)
    }

    @Test
    fun anIdleConnectionIsProbedBeforeItsNextRequest() {
        pool.call(root, login) { it }
        now += 10_000
        pool.call(root, login) { it }
        assertTrue(probed.isEmpty())
        now += 30_000
        pool.call(root, login) { it }
        assertEquals(listOf(1), probed)
    }

    @Test
    fun droppingARootClosesItsConnection() {
        pool.call(root, login) { it }
        pool.drop("r1")
        assertEquals(listOf(1), closed)
        assertEquals(2, pool.call(root, login) { it })
    }
}
