package io.github.iffix.neutrino.design

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * The place in the page header a page's own action goes to: taken while the sidebar is shown,
 * empty otherwise. The open page offers its action, and withdraws it when it closes.
 *
 * @property isHeader Whether the header draws the open page's action.
 */
class PageActionSlot(val isHeader: Boolean) {
    private var owner: Any? = null

    /** The action the header draws, or null for none. */
    var action: PageAction? by mutableStateOf(null)
        private set

    /**
     * Put one page's action in the header.
     *
     * @param owner The page offering it.
     * @param offered The action.
     */
    fun offer(owner: Any, offered: PageAction) {
        this.owner = owner
        action = offered
    }

    /**
     * Take one page's action out of the header; another page's action stays.
     *
     * @param owner The page withdrawing it.
     */
    fun withdraw(owner: Any) {
        if (this.owner !== owner) return
        this.owner = null
        action = null
    }
}

/** The header slot of the window the composition draws; a bare one draws nothing in a header. */
val LocalPageActionSlot = staticCompositionLocalOf { PageActionSlot(isHeader = false) }

/**
 * Offer the open page's action to the header.
 *
 * @param action The action.
 * @return Whether the header draws it; when false the page draws it itself.
 */
@Composable
fun offerPageAction(action: PageAction): Boolean {
    val slot = LocalPageActionSlot.current
    val owner = remember { Any() }
    if (slot.isHeader) SideEffect { slot.offer(owner, action) }
    DisposableEffect(slot) { onDispose { slot.withdraw(owner) } }
    return slot.isHeader
}
