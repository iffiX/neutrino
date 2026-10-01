package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_ZOOM_MAX

/**
 * Where the remote picture sits in the viewer: fitted whole at zoom 1, larger when pinched, and
 * never moved so far that an edge leaves a gap it could fill.
 *
 * @property viewWidth The viewer's width, in pixels.
 * @property viewHeight The viewer's height, in pixels.
 * @property frameWidth The remote picture's width, in its pixels; 0 before the first frame.
 * @property frameHeight The remote picture's height.
 * @property zoom The scale over the fitted one, from 1 to [RDP_ZOOM_MAX].
 * @property left Where the picture's left edge is, in the viewer's pixels.
 * @property top Where the picture's top edge is.
 */
data class RemoteDesktopViewport(
    val viewWidth: Float = 0f,
    val viewHeight: Float = 0f,
    val frameWidth: Int = 0,
    val frameHeight: Int = 0,
    val zoom: Float = 1f,
    val left: Float = 0f,
    val top: Float = 0f,
) {
    /** Viewer pixels per picture pixel. */
    val scale: Float
        get() = fitScale * zoom

    /** The picture's drawn width, in the viewer's pixels. */
    val drawnWidth: Float
        get() = if (hasFrame) frameWidth * scale else viewWidth

    /** The picture's drawn height. */
    val drawnHeight: Float
        get() = if (hasFrame) frameHeight * scale else viewHeight

    private val hasFrame: Boolean
        get() = frameWidth > 0 && frameHeight > 0 && viewWidth > 0f && viewHeight > 0f

    private val fitScale: Float
        get() = if (hasFrame) minOf(viewWidth / frameWidth, viewHeight / frameHeight) else 1f

    /**
     * The same picture in a viewer or of a frame of another size, fitted whole again.
     *
     * @param viewWidth The viewer's width.
     * @param viewHeight The viewer's height.
     * @param frameWidth The picture's width.
     * @param frameHeight The picture's height.
     * @return This viewport when nothing changed, else a fitted one.
     */
    fun sized(viewWidth: Float, viewHeight: Float, frameWidth: Int, frameHeight: Int): RemoteDesktopViewport {
        val isSame = viewWidth == this.viewWidth && viewHeight == this.viewHeight &&
            frameWidth == this.frameWidth && frameHeight == this.frameHeight
        if (isSame) return this
        return RemoteDesktopViewport(viewWidth, viewHeight, frameWidth, frameHeight).clamped()
    }

    /**
     * Zoom by a factor around a point that stays under the fingers.
     *
     * @param factor The change of scale.
     * @param focusX The point's x in the viewer.
     * @param focusY The point's y in the viewer.
     * @return The zoomed viewport.
     */
    fun zoomedBy(factor: Float, focusX: Float, focusY: Float): RemoteDesktopViewport {
        val next = (zoom * factor).coerceIn(1f, RDP_ZOOM_MAX)
        val ratio = next / zoom
        return copy(
            zoom = next,
            left = focusX - (focusX - left) * ratio,
            top = focusY - (focusY - top) * ratio,
        ).clamped()
    }

    /**
     * Move the picture with the fingers.
     *
     * @param dx The move to the right, in viewer pixels.
     * @param dy The move down.
     * @return The moved viewport.
     */
    fun pannedBy(dx: Float, dy: Float): RemoteDesktopViewport = copy(left = left + dx, top = top + dy).clamped()

    /**
     * The picture pixel under a point of the viewer, kept inside the picture.
     *
     * @param x The point's x in the viewer.
     * @param y The point's y in the viewer.
     * @return The pixel's column and row.
     */
    fun toFrame(x: Float, y: Float): Pair<Int, Int> {
        if (!hasFrame) return 0 to 0
        val column = ((x - left) / scale).toInt().coerceIn(0, frameWidth - 1)
        val row = ((y - top) / scale).toInt().coerceIn(0, frameHeight - 1)
        return column to row
    }

    private fun clamped(): RemoteDesktopViewport =
        copy(left = edge(left, viewWidth, drawnWidth), top = edge(top, viewHeight, drawnHeight))

    private fun edge(start: Float, view: Float, drawn: Float): Float =
        if (drawn <= view) (view - drawn) / 2f else start.coerceIn(view - drawn, 0f)
}
