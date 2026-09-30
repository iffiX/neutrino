package io.github.iffix.neutrino.binding

import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/**
 * Every hub this phone joined, and this installation's machine id, in one file sealed under the
 * Keystore's key.
 *
 * A file that is missing, or that the key cannot open, reads as no binding and a fresh id.
 *
 * @param file Where the sealed file lives.
 * @param sealer What seals it.
 */
class BindingStore(private val file: File, private val sealer: SecretSealer) {
    private val lock = Any()
    private var held: BindingFile = read()
    private val current = MutableStateFlow(held.bindings)

    /** Every binding, in the order joined. */
    val bindings: StateFlow<List<HubBinding>> = current.asStateFlow()

    /** This installation's id: a uuid4 hex made on the first read and kept. */
    val machineId: String
        get() = synchronized(lock) {
            if (held.machineId.isEmpty()) write(held.copy(machineId = UUID.randomUUID().toString().replace("-", "")))
            held.machineId
        }

    /**
     * Keep one binding; one with the same id is replaced where it stands.
     *
     * @param binding The binding.
     * @throws IOException When the file cannot be written.
     */
    fun put(binding: HubBinding) = synchronized(lock) {
        val list = held.bindings
        val index = list.indexOfFirst { it.id == binding.id }
        write(
            held.copy(
                bindings = if (index <
                    0
                ) {
                    list + binding
                } else {
                    list.toMutableList().also { it[index] = binding }
                },
            ),
        )
    }

    /**
     * Change one binding; an id nobody holds changes nothing.
     *
     * @param id The binding's id.
     * @param change What to make of it.
     * @return The binding as kept, or null when no binding has that id.
     * @throws IOException When the file cannot be written.
     */
    fun update(id: String, change: (HubBinding) -> HubBinding): HubBinding? = synchronized(lock) {
        val existing = held.bindings.firstOrNull { it.id == id } ?: return null
        val changed = change(existing)
        if (changed != existing) put(changed)
        changed
    }

    /**
     * Drop one binding.
     *
     * @param id The binding's id.
     * @throws IOException When the file cannot be written.
     */
    fun remove(id: String) = synchronized(lock) {
        write(held.copy(bindings = held.bindings.filterNot { it.id == id }))
    }

    /**
     * One binding.
     *
     * @param id The binding's id.
     * @return The binding, or null.
     */
    fun get(id: String): HubBinding? = held.bindings.firstOrNull { it.id == id }

    private fun read(): BindingFile {
        if (!file.exists()) return BindingFile()
        return try {
            json.decodeFromString(BindingFile.serializer(), String(sealer.open(file.readBytes()), Charsets.UTF_8))
        } catch (_: GeneralSecurityException) {
            BindingFile()
        } catch (_: SerializationException) {
            BindingFile()
        } catch (_: IllegalArgumentException) {
            BindingFile()
        } catch (_: IOException) {
            BindingFile()
        }
    }

    private fun write(next: BindingFile) {
        val sealed = sealer.seal(json.encodeToString(BindingFile.serializer(), next).toByteArray(Charsets.UTF_8))
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, file.name + ".part")
        temporary.writeBytes(sealed)
        if (!temporary.renameTo(file)) throw IOException("cannot replace ${file.name}")
        held = next
        current.value = next.bindings
    }

    @Serializable
    private data class BindingFile(
        @SerialName("machine_id") val machineId: String = "",
        val bindings: List<HubBinding> = emptyList(),
    )

    private companion object {
        val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
        }
    }
}
