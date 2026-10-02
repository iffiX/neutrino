package io.github.iffix.neutrino.shell

import androidx.compose.runtime.staticCompositionLocalOf

/** The actions every screen reaches without a parameter of its own; null in a preview. */
val LocalClientActions = staticCompositionLocalOf<ClientActions?> { null }
