package io.github.iffix.neutrino.scan

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Size
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.iffix.neutrino.SCAN_ANALYSIS_HEIGHT
import io.github.iffix.neutrino.SCAN_ANALYSIS_WIDTH
import io.github.iffix.neutrino.SCAN_VIBRATION_MILLIS
import java.util.concurrent.Executors

/**
 * The back camera's picture at 1920x1080, its centred square read for a QR code on every frame.
 * The first code read confirms with a haptic, stops the reading, and is handed over; a code
 * equal to [ignored] is passed over without either.
 *
 * @param onText Called on the main thread with the code's text.
 * @param ignored A code already tried, or empty; the reading starts again whenever it changes.
 * @param modifier Placement.
 */
@Composable
fun QrScanner(onText: (String) -> Unit, ignored: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val preview = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    val latest = rememberUpdatedState(onText)
    AndroidView(factory = { preview }, modifier = modifier)
    DisposableEffect(owner, ignored) {
        val executor = Executors.newSingleThreadExecutor()
        val main = ContextCompat.getMainExecutor(context)
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener(
            {
                val provider = future.get()
                val resolution = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            Size(SCAN_ANALYSIS_WIDTH, SCAN_ANALYSIS_HEIGHT),
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                        ),
                    )
                    .build()
                val picture = Preview.Builder().setResolutionSelector(resolution).build()
                    .also { it.surfaceProvider = preview.surfaceProvider }
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(resolution)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor) { image ->
                    val text = decode(image)
                    if (text != null && text != ignored) {
                        analysis.clearAnalyzer()
                        main.execute {
                            confirm(preview, context)
                            latest.value(text)
                        }
                    }
                }
                provider.unbindAll()
                provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, picture, analysis)
            },
            main,
        )
        onDispose {
            if (future.isDone) future.get().unbindAll()
            executor.shutdown()
        }
    }
}

private fun decode(image: ImageProxy): String? = image.use {
    val plane = it.planes[0]
    val buffer = plane.buffer
    val bytes = ByteArray(buffer.remaining()).also { target -> buffer.get(target) }
    QrFrameDecoder.decode(bytes, it.width, it.height, plane.rowStride, QrScanRegion.centred(it.width, it.height))
}

private fun confirm(view: View, context: Context) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
        return
    }
    val vibrator = context.getSystemService(Vibrator::class.java) ?: return
    vibrator.vibrate(VibrationEffect.createOneShot(SCAN_VIBRATION_MILLIS, VibrationEffect.DEFAULT_AMPLITUDE))
}
