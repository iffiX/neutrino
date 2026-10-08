package io.github.iffix.neutrino

import android.util.Log
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * The scope every session and service of the app runs in. A child that fails ends alone: the
 * failure goes to [onFailure], its siblings and the scope go on, and a cancelled child is not a
 * failure.
 *
 * @param onFailure Called with each exception a child did not catch; the default logs it under [CLIENT_LOG_TAG].
 * @return The scope.
 */
fun appScope(onFailure: (Throwable) -> Unit = ::logFailure): CoroutineScope =
    CoroutineScope(SupervisorJob() + Dispatchers.Default + CoroutineExceptionHandler { _, error -> onFailure(error) })

private fun logFailure(error: Throwable) {
    Log.e(CLIENT_LOG_TAG, "a job of the app's scope failed", error)
}
