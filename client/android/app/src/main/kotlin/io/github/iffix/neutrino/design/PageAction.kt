package io.github.iffix.neutrino.design

/**
 * A page's own action, such as New terminal or Scan: drawn in the page's header beside the
 * sidebar, and by the page itself in the bottom-bar layout.
 *
 * @property label What its button says.
 * @property icon The icon before the label, or null for none.
 * @property isEnabled Whether it takes presses.
 * @property onClick What a press does.
 */
data class PageAction(val label: String, val icon: AppIcon?, val isEnabled: Boolean, val onClick: () -> Unit)
