package io.github.iffix.neutrino

import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AppScopeTest {
    @Test
    fun aChildThatThrowsIsReportedAndTheScopeAndItsSiblingsGoOn() = runBlocking {
        val failures = CopyOnWriteArrayList<Throwable>()
        val scope = appScope { failures += it }
        val sibling = scope.launch { awaitCancellation() }
        scope.launch { throw IllegalStateException("boom") }.join()
        assertEquals(listOf("boom"), failures.map { it.message })
        assertTrue(scope.isActive)
        assertTrue(sibling.isActive)
        assertEquals(2, scope.async { 1 + 1 }.await())
        scope.cancel()
    }

    @Test
    fun aCancelledChildIsNoFailure() = runBlocking {
        val failures = CopyOnWriteArrayList<Throwable>()
        val scope = appScope { failures += it }
        scope.launch { awaitCancellation() }.cancelAndJoin()
        assertEquals(emptyList<Throwable>(), failures)
        assertTrue(scope.isActive)
        scope.cancel()
    }
}
