package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_LIBRARY_CLASS
import io.github.iffix.neutrino.TransportMissingException
import java.io.IOException
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Method

/**
 * The transport's gomobile library, bound into one `.aar` with NetBird's: the class gomobile
 * binds `transport/mobile` to, found by its name when the app runs, so a build without the
 * library still builds and says so at the first start.
 *
 * @param className The class whose static `start(String, String): String` and `stop()` the library binds.
 */
class GomobileTransportLibrary(private val className: String = TRANSPORT_LIBRARY_CLASS) : TransportLibrary {
    override fun start(directory: String, secret: String): String {
        val start = methodOf("start", String::class.java, String::class.java)
        return try {
            start.invoke(null, directory, secret) as? String ?: throw IOException("the transport named no socket")
        } catch (error: InvocationTargetException) {
            val cause = error.targetException
            throw IOException(cause?.message ?: "the transport did not start", cause)
        }
    }

    override fun stop() {
        try {
            methodOf("stop").invoke(null)
        } catch (_: TransportMissingException) {
            return
        } catch (_: InvocationTargetException) {
            return
        }
    }

    private fun methodOf(name: String, vararg types: Class<*>): Method = try {
        Class.forName(className).getMethod(name, *types)
    } catch (_: ClassNotFoundException) {
        throw TransportMissingException(className)
    } catch (_: NoSuchMethodException) {
        throw TransportMissingException(className)
    } catch (_: LinkageError) {
        throw TransportMissingException(className)
    }
}
