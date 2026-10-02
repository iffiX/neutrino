package io.github.iffix.neutrino.forward

import java.io.ByteArrayInputStream
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WebTokenHeadersTest {
    private fun head(vararg lines: String) = lines.joinToString("\r\n") + "\r\n\r\n"

    @Test
    fun aRequestTakesTheTokenCookieAndConnectionClose() {
        val sent = WebTokenHeaders.request(
            head("GET / HTTP/1.1", "Host: 127.0.0.1:8000", "Connection: keep-alive"),
            "t0k",
        )
        assertEquals(
            head("GET / HTTP/1.1", "Host: 127.0.0.1:8000", "Cookie: vscode-tkn=t0k", "Connection: close"),
            sent,
        )
    }

    @Test
    fun aTokenCookieTheBrowserSentIsReplacedAndTheOthersKept() {
        val sent = WebTokenHeaders.request(
            head("GET /a HTTP/1.1", "Cookie: vscode-tkn=old; theme=dark", "cookie: lang=en"),
            "new",
        )
        assertEquals(head("GET /a HTTP/1.1", "Cookie: theme=dark; lang=en; vscode-tkn=new", "Connection: close"), sent)
    }

    @Test
    fun anUpgradeKeepsItsConnectionHeader() {
        val sent = WebTokenHeaders.request(
            head("GET /ws HTTP/1.1", "Connection: Upgrade", "Upgrade: websocket"),
            "t",
        )
        assertEquals(
            head("GET /ws HTTP/1.1", "Connection: Upgrade", "Upgrade: websocket", "Cookie: vscode-tkn=t"),
            sent,
        )
    }

    @Test
    fun aResponseLosesTheTokensSetCookieAndKeepsTheRest() {
        val passed = WebTokenHeaders.response(
            head(
                "HTTP/1.1 200 OK",
                "Set-Cookie: vscode-tkn=t; Path=/",
                "set-cookie: theme=dark",
                "Content-Length: 2",
            ),
        )
        assertEquals(head("HTTP/1.1 200 OK", "set-cookie: theme=dark", "Content-Length: 2"), passed)
    }

    @Test
    fun anUpgradeResponseIsPassedUntouched() {
        val upgrade = head("HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Set-Cookie: vscode-tkn=t")
        assertEquals(upgrade, WebTokenHeaders.response(upgrade))
    }

    @Test
    fun aHeadIsReadUpToItsBlankLineWithTheBytesPastIt() {
        val (text, rest) = requireNotNull(
            WebTokenHeaders.read(ByteArrayInputStream("POST / HTTP/1.1\r\nA: b\r\n\r\nbody".toByteArray())),
        )
        assertEquals("POST / HTTP/1.1\r\nA: b\r\n\r\n", text)
        assertArrayEquals("body".toByteArray(), rest)
    }

    @Test
    fun aConnectionThatEndsBeforeTheBlankLineHasNoHead() {
        assertNull(WebTokenHeaders.read(ByteArrayInputStream("GET / HTTP/1.1\r\n".toByteArray())))
    }
}
