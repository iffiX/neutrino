package io.github.iffix.neutrino.screen

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import io.github.iffix.neutrino.SCAN_REGION_FRACTION
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubJoin
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.ErrorLine
import io.github.iffix.neutrino.design.InputField
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.scan.QrScanner

/**
 * Joining a hub: the camera reads the QR code on the hub's Clients page, or the person pastes
 * the link; either starts the join, and Join shows it until the hub answers.
 *
 * @param join The join the app core runs.
 * @param onJoin What joining with a link's text does.
 * @param onJoined What happens once the hub is joined.
 */
@Composable
fun JoinScreen(join: HubJoin, onJoin: (String) -> Unit, onJoined: () -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    var link by remember { mutableStateOf("") }
    var scanned by remember { mutableStateOf("") }
    var ignored by remember { mutableStateOf("") }
    LaunchedEffect(join.joinedId) { if (join.joinedId != null) onJoined() }
    LaunchedEffect(join.refusal) { if (join.refusal != null && scanned.isNotEmpty()) ignored = scanned }
    ScreenColumn {
        CameraFrame(
            ignored = ignored,
            onText = { text ->
                scanned = text
                onJoin(text)
            },
        )
        BasicText(
            words.word("ui.scan_hint"),
            style = NeutrinoTheme.note.copy(color = palette.textFaint, textAlign = TextAlign.Center),
            modifier = Modifier.fillMaxWidth(),
        )
        OrRule()
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BasicText(words.word("ui.paste_hint"), style = NeutrinoTheme.fieldLabel)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                InputField(
                    value = link,
                    onChange = { link = it },
                    label = words.word("ui.paste_hint"),
                    placeholder = "neutrino://enroll/...",
                    modifier = Modifier.weight(1f),
                    onDone = {
                        scanned = ""
                        onJoin(link)
                    },
                )
                NeutrinoButton(
                    words.word(if (join.isJoining) "ui.job.joining" else "ui.join"),
                    {
                        scanned = ""
                        onJoin(link)
                    },
                    tier = ButtonTier.PRIMARY,
                    isEnabled = !join.isJoining,
                    isBusy = join.isJoining,
                )
            }
            ErrorLine(join.refusal?.takeIf { !join.isJoining })
        }
    }
}

@Composable
private fun CameraFrame(ignored: String, onText: (String) -> Unit) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val context = LocalContext.current
    val isPreview = LocalInspectionMode.current
    var isAllowed by remember {
        mutableStateOf(
            !isPreview &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var isRefused by remember { mutableStateOf(false) }
    val request = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        isAllowed = granted
        isRefused = !granted
    }
    val shape = RoundedCornerShape(14.dp)
    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Box(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(shape)
                .background(palette.termBg)
                .border(1.dp, palette.border, shape),
            contentAlignment = Alignment.Center,
        ) {
            if (isAllowed) {
                QrScanner(onText = onText, ignored = ignored, modifier = Modifier.fillMaxSize())
            } else if (isRefused) {
                BasicText(
                    words.word("ui.camera_refused"),
                    style = NeutrinoTheme.note.copy(textAlign = TextAlign.Center),
                    modifier = Modifier.padding(24.dp),
                )
            } else {
                NeutrinoButton(words.word("ui.camera_allow"), { request.launch(Manifest.permission.CAMERA) })
            }
            Box(modifier = Modifier.fillMaxSize().drawBehind { drawCorners(palette.accent) })
        }
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawCorners(color: androidx.compose.ui.graphics.Color) {
    val arm = 34.dp.toPx()
    val inset = size.width * (1f - SCAN_REGION_FRACTION) / 2f
    val stroke = 2.dp.toPx()
    val far = size.width - inset
    val corners = listOf(
        Offset(inset, inset) to Pair(1f, 1f),
        Offset(far, inset) to Pair(-1f, 1f),
        Offset(inset, far) to Pair(1f, -1f),
        Offset(far, far) to Pair(-1f, -1f),
    )
    for ((point, direction) in corners) {
        drawLine(color, point, Offset(point.x + arm * direction.first, point.y), stroke, StrokeCap.Round)
        drawLine(color, point, Offset(point.x, point.y + arm * direction.second), stroke, StrokeCap.Round)
    }
}

@Composable
private fun OrRule() {
    val palette = NeutrinoTheme.palette
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(modifier = Modifier.weight(1f).drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f)) })
        BasicText(NeutrinoTheme.words.word("ui.or"), style = NeutrinoTheme.note.copy(color = palette.textFaint))
        Box(modifier = Modifier.weight(1f).drawBehind { drawLine(palette.border, Offset.Zero, Offset(size.width, 0f)) })
    }
}

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun JoinScreenPreview() {
    PreviewHubs.Frame(
        mapOf(
            "ui.scan_hint" to "对准 hub 客户端页面上的二维码",
            "ui.or" to "或",
            "ui.paste_hint" to "粘贴 hub 客户端页面上的链接",
            "ui.join" to "加入",
            "ui.camera_allow" to "允许使用相机",
        ),
    ) { JoinScreen(HubJoin(refusal = ChannelResult.refused("link_unreadable")), onJoin = {}, onJoined = {}) }
}
