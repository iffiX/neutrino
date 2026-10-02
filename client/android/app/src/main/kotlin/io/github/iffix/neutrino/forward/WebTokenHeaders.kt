package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.FORWARD_HEAD_MAX_BYTES
import io.github.iffix.neutrino.WEB_TOKEN_COOKIE
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream

/**
 * The header rewrite of a local-only web entry's forward: each request carries the entry's
 * token as the `vscode-tkn` cookie and `Connection: close`, and each response loses the
 * server's `Set-Cookie` for that cookie. A WebSocket upgrade keeps its `Connection` header, and
 * a `101` response passes untouched.
 */
object WebTokenHeaders {
    private const val END = "\r\n\r\n"

    /**
     * Read one message's head, up to and with its blank line.
     *
     * @param input The connection.
     * @return The head as text, and the bytes read past it; null when the connection ends first.
     * @throws IOException When the connection fails, or the head is longer than 64 KiB.
     */
    fun read(input: InputStream): Pair<String, ByteArray>? {
        val held = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) return null
            held.write(buffer, 0, count)
            val text = held.toString(Charsets.ISO_8859_1.name())
            val end = text.indexOf(END)
            if (end >= 0) {
                val bytes = held.toByteArray()
                return text.substring(0, end + END.length) to bytes.copyOfRange(end + END.length, bytes.size)
            }
            if (held.size() > FORWARD_HEAD_MAX_BYTES) throw IOException("the message head is too long")
        }
    }

    /**
     * A request's head with the token in its cookie and, unless it upgrades, `Connection: close`.
     *
     * @param head The head as the browser sent it, ending in the blank line.
     * @param token The entry's token.
     * @return The head to send on.
     */
    fun request(head: String, token: String): String {
        val (start, fields) = split(head)
        val isUpgrade = fields.any { (name, value) ->
            name.equals("Connection", ignoreCase = true) && value.contains("upgrade", ignoreCase = true)
        }
        val cookies = fields.filter { it.first.equals("Cookie", ignoreCase = true) }
            .flatMap { (_, value) -> value.split(';') }
            .map { it.trim() }
            .filter { it.isNotEmpty() && it.substringBefore('=').trim() != WEB_TOKEN_COOKIE }
        val kept = fields.filterNot { (name, _) ->
            name.equals("Cookie", ignoreCase = true) || (!isUpgrade && name.equals("Connection", ignoreCase = true))
        }
        val added = buildList {
            add("Cookie" to (cookies + "$WEB_TOKEN_COOKIE=$token").joinToString("; "))
            if (!isUpgrade) add("Connection" to "close")
        }
        return join(start, kept + added)
    }

    /**
     * A response's head without the server's `Set-Cookie` for the token; a `101` is left as it is.
     *
     * @param head The head as the server sent it, ending in the blank line.
     * @return The head to pass to the browser.
     */
    fun response(head: String): String {
        val (start, fields) = split(head)
        if (start.split(' ').getOrNull(1) == "101") return head
        val kept = fields.filterNot { (name, value) ->
            name.equals("Set-Cookie", ignoreCase = true) && value.substringBefore('=').trim() == WEB_TOKEN_COOKIE
        }
        return join(start, kept)
    }

    private fun split(head: String): Pair<String, List<Pair<String, String>>> {
        val lines = head.removeSuffix(END).split("\r\n")
        val fields = lines.drop(1).filter { ':' in it }.map { it.substringBefore(':') to it.substringAfter(':').trim() }
        return lines.first() to fields
    }

    private fun join(start: String, fields: List<Pair<String, String>>): String =
        (listOf(start) + fields.map { (name, value) -> "$name: $value" }).joinToString("\r\n") + END
}
