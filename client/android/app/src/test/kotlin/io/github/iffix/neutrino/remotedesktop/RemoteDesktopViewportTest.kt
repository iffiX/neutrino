package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.RDP_ZOOM_MAX
import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteDesktopViewportTest {
    // A 1000 x 1000 viewer showing a 2000 x 1000 picture: fitted at half scale, 250 px bands above and below.
    private val fitted = RemoteDesktopViewport().sized(1000f, 1000f, 2000, 1000)

    @Test
    fun aNewFramePictureIsFittedWholeAndCentred() {
        assertEquals(0.5f, fitted.scale, 0.0001f)
        assertEquals(0f, fitted.left, 0.0001f)
        assertEquals(250f, fitted.top, 0.0001f)
        assertEquals(1000f, fitted.drawnWidth, 0.0001f)
        assertEquals(500f, fitted.drawnHeight, 0.0001f)
    }

    @Test
    fun aViewerPointMapsToThePicturePixelUnderIt() {
        assertEquals(1000 to 500, fitted.toFrame(500f, 500f))
        assertEquals(0 to 0, fitted.toFrame(0f, 250f))
    }

    @Test
    fun aPointOutsideThePictureMapsToItsNearestEdge() {
        assertEquals(0 to 0, fitted.toFrame(-10f, 0f))
        assertEquals(1999 to 999, fitted.toFrame(5000f, 5000f))
    }

    @Test
    fun aPinchKeepsThePointUnderTheFingers() {
        val zoomed = fitted.zoomedBy(2f, 500f, 500f)
        assertEquals(2f, zoomed.zoom, 0.0001f)
        assertEquals(fitted.toFrame(500f, 500f), zoomed.toFrame(500f, 500f))
    }

    @Test
    fun zoomStaysBetweenFittedAndTheMaximum() {
        assertEquals(1f, fitted.zoomedBy(0.2f, 500f, 500f).zoom, 0.0001f)
        assertEquals(RDP_ZOOM_MAX, fitted.zoomedBy(100f, 500f, 500f).zoom, 0.0001f)
    }

    @Test
    fun aPanStopsWhereAnEdgeWouldLeaveAGap() {
        val zoomed = fitted.zoomedBy(4f, 0f, 500f)
        val far = zoomed.pannedBy(100000f, 100000f)
        assertEquals(0f, far.left, 0.0001f)
        assertEquals(0f, far.top, 0.0001f)
        val other = zoomed.pannedBy(-100000f, -100000f)
        assertEquals(1000f - other.drawnWidth, other.left, 0.0001f)
        assertEquals(1000f - other.drawnHeight, other.top, 0.0001f)
    }

    @Test
    fun aSmallerSideStaysCentredWhilePanned() {
        val moved = fitted.pannedBy(0f, 300f)
        assertEquals(250f, moved.top, 0.0001f)
    }

    @Test
    fun anotherFrameSizeFitsThePictureAgain() {
        val resized = fitted.zoomedBy(3f, 500f, 500f).sized(1000f, 1000f, 1000, 1000)
        assertEquals(1f, resized.zoom, 0.0001f)
        assertEquals(1f, resized.scale, 0.0001f)
        assertEquals(0f, resized.left, 0.0001f)
    }

    @Test
    fun beforeTheFirstFrameThePictureFillsTheViewer() {
        val empty = RemoteDesktopViewport().sized(800f, 600f, 0, 0)
        assertEquals(800f, empty.drawnWidth, 0.0001f)
        assertEquals(600f, empty.drawnHeight, 0.0001f)
        assertEquals(0 to 0, empty.toFrame(400f, 300f))
    }

    @Test
    fun theKeyboardLeavesThePictureWhereItIs() {
        val covered = fitted.coveredBy(400f)
        assertEquals(fitted.top, covered.top, 0.0001f)
        assertEquals(fitted.drawnHeight, covered.drawnHeight, 0.0001f)
    }

    @Test
    fun underTheKeyboardThePictureMovesUpUntilItsBottomMeetsIt() {
        val covered = fitted.coveredBy(400f).zoomedBy(2f, 500f, 500f).pannedBy(0f, -5000f)
        assertEquals(1000f - 400f - covered.drawnHeight, covered.top, 0.0001f)
        assertEquals(1000f - covered.drawnHeight, covered.coveredBy(0f).top, 0.0001f)
    }
}
