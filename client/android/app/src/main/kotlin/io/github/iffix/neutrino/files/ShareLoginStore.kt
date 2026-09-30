package io.github.iffix.neutrino.files

import io.github.iffix.neutrino.binding.SecretSealer
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The share logins: the kept ones in a file sealed under the Keystore's key, and the ones given
 * for this run only in memory.
 *
 * @param file Where the kept logins are sealed.
 * @param sealer What seals them.
 */
class ShareLoginStore(private val file: File, private val sealer: SecretSealer) {
    private val json = Json { ignoreUnknownKeys = true }
    private val serializer = MapSerializer(String.serializer(), ShareLogin.serializer())
    private val kept: MutableMap<String, ShareLogin> = read().toMutableMap()
    private val forNow = mutableMapOf<String, ShareLogin>()

    /**
     * The login of one share.
     *
     * @param key The share's root id.
     * @return The login, or null when none was given.
     */
    @Synchronized
    fun get(key: String): ShareLogin? = forNow[key] ?: kept[key]

    /**
     * Whether a share's login is kept across runs.
     *
     * @param key The share's root id.
     * @return True when it is.
     */
    @Synchronized
    fun isKept(key: String): Boolean = key in kept

    /**
     * Give a share's login.
     *
     * @param key The share's root id.
     * @param login The login.
     * @param isKept Whether it is kept across runs, sealed, or held for this run only.
     * @throws IOException When the kept file cannot be written.
     */
    @Synchronized
    fun put(key: String, login: ShareLogin, isKept: Boolean) {
        forNow.remove(key)
        if (isKept) {
            kept[key] = login
            write()
        } else {
            forNow[key] = login
            if (kept.remove(key) != null) write()
        }
    }

    /**
     * Forget a share's login, as after the server rejected it.
     *
     * @param key The share's root id.
     * @throws IOException When the kept file cannot be written.
     */
    @Synchronized
    fun forget(key: String) {
        forNow.remove(key)
        if (kept.remove(key) != null) write()
    }

    private fun read(): Map<String, ShareLogin> {
        if (!file.exists()) return emptyMap()
        return try {
            json.decodeFromString(serializer, String(sealer.open(file.readBytes()), Charsets.UTF_8))
        } catch (_: GeneralSecurityException) {
            emptyMap()
        } catch (_: SerializationException) {
            emptyMap()
        } catch (_: IOException) {
            emptyMap()
        }
    }

    private fun write() {
        val sealed = try {
            sealer.seal(json.encodeToString(serializer, kept).toByteArray(Charsets.UTF_8))
        } catch (error: GeneralSecurityException) {
            throw IOException("cannot seal the share logins", error)
        }
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, file.name + ".part")
        temporary.writeBytes(sealed)
        if (!temporary.renameTo(file)) throw IOException("cannot replace ${file.name}")
    }
}
