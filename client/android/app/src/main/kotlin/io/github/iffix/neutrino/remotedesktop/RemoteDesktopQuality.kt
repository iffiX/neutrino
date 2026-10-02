package io.github.iffix.neutrino.remotedesktop

/**
 * The picture quality a remote desktop session asks for, as RustDesk's `image-quality` names it.
 *
 * @property coreName The option's value in the core.
 * @property wordKey The catalog key the picker shows.
 */
enum class RemoteDesktopQuality(val coreName: String, val wordKey: String) {
    /** RustDesk's default trade between the picture and the bandwidth. */
    BALANCED("balanced", "ui.rdp_quality_balanced"),

    /** Fewer bits per frame for a slow network. */
    LOW("low", "ui.rdp_quality_low"),

    /** The best picture the network carries. */
    BEST("best", "ui.rdp_quality_best"),
    ;

    companion object {
        /**
         * A quality by its core name.
         *
         * @param coreName The name kept in the settings.
         * @return The quality, or [BALANCED] for a name the app does not know.
         */
        fun of(coreName: String): RemoteDesktopQuality = entries.firstOrNull { it.coreName == coreName } ?: BALANCED
    }
}
