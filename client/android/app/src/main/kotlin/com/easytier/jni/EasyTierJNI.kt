package com.easytier.jni

/**
 * EasyTier's JNI binding, `libeasytier_android_jni.so` built by `packaging/build/build_core_easytier.py`.
 *
 * The package and the names are the ones the library's exported symbols spell, so they are
 * upstream's, not this app's.
 */
object EasyTierJNI {
    init {
        System.loadLibrary("easytier_android_jni")
    }

    /**
     * Hand a network instance its TUN device.
     *
     * @param instanceName The instance.
     * @param fd The TUN device's descriptor.
     * @return 0 on success.
     * @throws RuntimeException When the instance does not take it.
     */
    @JvmStatic external fun setTunFd(instanceName: String, fd: Int): Int

    /**
     * Check a TOML configuration.
     *
     * @param config The configuration.
     * @return 0 when it reads.
     * @throws RuntimeException When it does not.
     */
    @JvmStatic external fun parseConfig(config: String): Int

    /**
     * Run a network instance from a TOML configuration.
     *
     * @param config The configuration.
     * @return 0 on success.
     * @throws RuntimeException When the instance does not start.
     */
    @JvmStatic external fun runNetworkInstance(config: String): Int

    /**
     * Keep the named instances and stop every other.
     *
     * @param instanceNames The instances to keep; null or empty stops them all.
     * @return 0 on success.
     * @throws RuntimeException When stopping fails.
     */
    @JvmStatic external fun retainNetworkInstance(instanceNames: Array<String>?): Int

    /**
     * Every running instance's state.
     *
     * @return `{"map": {name: running info}}` as JSON, or null.
     * @throws RuntimeException When the state cannot be read.
     */
    @JvmStatic external fun collectNetworkInfos(): String?

    /**
     * The last error the library recorded.
     *
     * @return The message, or null.
     */
    @JvmStatic external fun getLastError(): String?

    /**
     * Start a console's web client: the console pushes the networks it runs.
     *
     * @param server The console's address with its account token.
     * @param name The name this phone shows in the console.
     * @param dir Where the client keeps its machine id.
     * @param isSecure Whether the console is spoken to over its secure tunnel.
     * @return 0 on success.
     * @throws RuntimeException When the client does not start.
     */
    @JvmStatic external fun runWebClient(server: String, name: String, dir: String, isSecure: Boolean): Int

    /**
     * Stop the web client and every network it started.
     *
     * @return 0 on success.
     * @throws RuntimeException When stopping fails.
     */
    @JvmStatic external fun stopWebClient(): Int

    /**
     * Whether the web client holds a session with its console.
     *
     * @return True while it does.
     */
    @JvmStatic external fun isWebClientConnected(): Boolean
}
