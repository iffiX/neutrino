package io.github.iffix.neutrino.design

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A one-line text field in the panel's style: mono text on the background, the accent border
 * while focused.
 *
 * @param value The text.
 * @param onChange What typing does.
 * @param label What a screen reader calls it.
 * @param modifier Placement.
 * @param placeholder What the empty field shows.
 * @param isSecret Whether the text is a password, drawn as dots.
 * @param onDone What the keyboard's done key does.
 */
@Composable
fun InputField(
    value: String,
    onChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    isSecret: Boolean = false,
    onDone: () -> Unit = {},
) {
    val palette = NeutrinoTheme.palette
    var isFocused by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(6.dp)
    val style = NeutrinoTheme.mono.copy(color = palette.text, fontSize = 13.sp)
    BasicTextField(
        value = value,
        onValueChange = onChange,
        singleLine = true,
        textStyle = style,
        cursorBrush = SolidColor(palette.accent),
        visualTransformation = if (isSecret) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (isSecret) KeyboardType.Password else KeyboardType.Uri,
            imeAction = ImeAction.Done,
            autoCorrectEnabled = false,
        ),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        modifier = modifier
            .semantics { contentDescription = label }
            .onFocusChanged { isFocused = it.isFocused },
        decorationBox = { inner ->
            Box(
                modifier = Modifier
                    .clip(shape)
                    .background(palette.bg)
                    .border(1.dp, if (isFocused) palette.accent else palette.border, shape)
                    .padding(horizontal = 11.dp, vertical = 9.dp),
            ) {
                if (value.isEmpty() && placeholder.isNotEmpty()) {
                    BasicText(placeholder, style = style.copy(color = palette.textFaint))
                }
                inner()
            }
        },
    )
}
