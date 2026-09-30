package io.github.iffix.neutrino

import java.io.File

/** Files of the repository the tests read by their path, never from a copy. */
object RepositoryFiles {
    /** The repository's root, which the Gradle test task names. */
    val root: File
        get() = File(
            System.getProperty("neutrino.repositoryRoot")
                ?: throw IllegalStateException("the test task names neutrino.repositoryRoot"),
        )

    /**
     * One file of the repository.
     *
     * @param path Its path from the root.
     * @return The file.
     */
    fun file(path: String): File = root.resolve(path)

    /**
     * One file's text.
     *
     * @param path Its path from the root.
     * @return The text.
     */
    fun text(path: String): String = file(path).readText()
}
