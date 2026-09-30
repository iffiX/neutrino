import java.awt.Image
import java.awt.image.BufferedImage
import java.util.Base64
import javax.imageio.ImageIO

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ktlint)
}

val neutrinoVersion: String = providers.gradleProperty("neutrinoVersion").get()
val repositoryRoot: File = rootDir.resolve("../..")

// 0.5.0 is 500: two digits each for the minor and the patch.
fun versionCodeOf(version: String): Int {
    val (major, minor, patch) = version.substringBefore('-').split('.').map { it.toInt() }
    return major * 10000 + minor * 100 + patch
}

// The release key arrives in four environment variables; the keystore itself as
// base64, decoded into the build directory for the signing step.
val releaseKeystore: File? =
    System.getenv("ANDROID_KEYSTORE_B64")?.takeIf { it.isNotBlank() }?.let { encoded ->
        layout.buildDirectory.file("signing/release.jks").get().asFile.apply {
            parentFile.mkdirs()
            writeBytes(Base64.getMimeDecoder().decode(encoded))
        }
    }

android {
    namespace = "io.github.iffix.neutrino"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.iffix.neutrino"
        minSdk = 26
        targetSdk = 35
        versionName = neutrinoVersion
        versionCode = versionCodeOf(neutrinoVersion)
    }

    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = releaseKeystore
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    // One apk per machine: arm64-v8a is the one published, x86_64 runs in
    // the emulator.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "x86_64")
            isUniversalApk = false
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    lint {
        abortOnError = true
        warningsAsErrors = true
        checkReleaseBuilds = true
        // Whether a newer release exists changes with the day, not the code; the
        // target API is a decision of the release, not of lint.
        disable += setOf("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion", "OldTargetApi")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

ktlint {
    version.set(libs.versions.ktlint.cli.get())
    android.set(true)
}

// Files of the repository copied into the app's assets at build time, so the
// app carries the desktop client's word catalogs and its terminal as they are.
abstract class RepositoryAssetsCopy : DefaultTask() {
    @get:InputFiles
    abstract val sources: ConfigurableFileCollection

    @get:Input
    abstract val into: Property<String>

    @get:OutputDirectory
    abstract val output: DirectoryProperty

    @TaskAction
    fun copy() {
        val target = output.get().asFile.resolve(into.get())
        target.deleteRecursively()
        target.mkdirs()
        sources.files.forEach { file -> file.copyTo(target.resolve(file.name), overwrite = true) }
    }
}

// The launcher icon's foreground, drawn from images/icons at each density: the
// mark fills 72 of the 108 units an adaptive icon's layer spans.
abstract class LauncherIconRender : DefaultTask() {
    @get:InputFile
    abstract val source: RegularFileProperty

    @get:OutputDirectory
    abstract val output: DirectoryProperty

    @TaskAction
    fun render() {
        val mark = ImageIO.read(source.get().asFile)
        val edges = mapOf("mdpi" to 108, "hdpi" to 162, "xhdpi" to 216, "xxhdpi" to 324, "xxxhdpi" to 432)
        for ((density, edge) in edges) {
            val inner = edge * 72 / 108
            val canvas = BufferedImage(edge, edge, BufferedImage.TYPE_INT_ARGB)
            val graphics = canvas.createGraphics()
            val scaled = mark.getScaledInstance(inner, inner, Image.SCALE_AREA_AVERAGING)
            graphics.drawImage(scaled, (edge - inner) / 2, (edge - inner) / 2, null)
            graphics.dispose()
            val directory = output.get().asFile.resolve("mipmap-$density")
            directory.mkdirs()
            ImageIO.write(canvas, "png", directory.resolve("ic_launcher_foreground.png"))
        }
    }
}

val launcherIconRender =
    tasks.register<LauncherIconRender>("launcherIconRender") {
        source.set(repositoryRoot.resolve("images/icons/neutrino_512.png"))
        output.set(layout.buildDirectory.dir("generated/launcher_icon"))
    }

val desktopLocalesCopy =
    tasks.register<RepositoryAssetsCopy>("desktopLocalesCopy") {
        sources.from(repositoryRoot.resolve("client/desktop/frontend/locales/en.json"))
        sources.from(repositoryRoot.resolve("client/desktop/frontend/locales/zh-CN.json"))
        into.set("locales/desktop")
        output.set(layout.buildDirectory.dir("generated/desktop_locales"))
    }

val terminalVendorCopy =
    tasks.register<RepositoryAssetsCopy>("terminalVendorCopy") {
        sources.from(repositoryRoot.resolve("client/desktop/frontend/vendor/xterm.js"))
        sources.from(repositoryRoot.resolve("client/desktop/frontend/vendor/xterm.css"))
        sources.from(repositoryRoot.resolve("client/desktop/frontend/vendor/addon-fit.js"))
        sources.from(repositoryRoot.resolve("hub/frontend/src/fonts/MesloLGSNF-Regular.ttf"))
        sources.from(repositoryRoot.resolve("hub/frontend/src/fonts/MesloLGSNF-Bold.ttf"))
        into.set("terminal/vendor")
        output.set(layout.buildDirectory.dir("generated/terminal_vendor"))
    }

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(desktopLocalesCopy, RepositoryAssetsCopy::output)
        variant.sources.assets?.addGeneratedSourceDirectory(terminalVendorCopy, RepositoryAssetsCopy::output)
        variant.sources.res?.addGeneratedSourceDirectory(launcherIconRender, LauncherIconRender::output)
    }
}

tasks.withType<Test>().configureEach {
    systemProperty("neutrino.repositoryRoot", repositoryRoot.absolutePath)
    inputs.dir(repositoryRoot.resolve("client/desktop/frontend/locales"))
    inputs.file(repositoryRoot.resolve("hub/tests/web/channel_schema.json"))
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.foundation)
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    implementation(files("libs/netbird.aar"))
    implementation(libs.zxing.core)
    implementation(libs.smbj)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.view)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.okhttp.tls)
}
