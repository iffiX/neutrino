package io.github.iffix.neutrino.design

/**
 * The panel's icon set: 24 by 24 outlines, stroked in the colour they are drawn in.
 *
 * @property paths The SVG path data of each stroke.
 */
enum class AppIcon(val paths: List<String>) {
    SERVER(
        listOf(
            "M5 3h14a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
            "M5 14h14a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z",
            "M7 6.5h.01M7 17.5h.01",
        ),
    ),
    APPS(listOf("M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z")),
    FOLDER(listOf("M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z")),
    TERMINAL(listOf("m4 17 6-5-6-5", "M12 19h8")),
    DESKTOP(
        listOf(
            "M5 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
            "M9 20h6",
            "M12 16v4",
        ),
    ),
    SETTINGS(listOf("M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3", "M1 14h6M9 8h6M17 16h6")),
    CHEVRON_RIGHT(listOf("m9 6 6 6-6 6")),
    CHEVRON_LEFT(listOf("m15 6-6 6 6 6")),
    CHEVRON_DOWN(listOf("m6 9 6 6 6-6")),
    CHEVRON_UP(listOf("m6 15 6-6 6 6")),
    CLOSE(listOf("m6 6 12 12M18 6 6 18")),
    LOCK(
        listOf(
            "M6 10h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z",
            "M8 10V7a4 4 0 0 1 8 0v3",
        ),
    ),
    PLUS(listOf("M12 5v14M5 12h14")),
    KEYBOARD(
        listOf(
            "M4 6h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
            "M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8",
        ),
    ),
    COMMAND(listOf("M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3")),
    CAMERA(
        listOf(
            "M3 8h4l2-3h6l2 3h4v11H3z",
            "M8.5 13a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0",
        ),
    ),
    LINK(
        listOf(
            "M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1",
            "M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1",
        ),
    ),
    REFRESH(listOf("M20 12a8 8 0 1 1-2.34-5.66L20 8.5", "M20 3.5v5h-5")),
}
