import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.animan.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.animan.app"
        minSdk = 29
        targetSdk = 35
        versionCode = 211
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        create("release") {
            val keyPath = System.getenv("ANIMAN_ANDROID_KEYSTORE")
            if (!keyPath.isNullOrBlank()) {
                storeFile = file(keyPath)
                storePassword = System.getenv("ANIMAN_ANDROID_STORE_PASSWORD")
                keyAlias = System.getenv("ANIMAN_ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANIMAN_ANDROID_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            isMinifyEnabled = false
        }
        create("validation") {
            initWith(getByName("release"))
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
        }
    }
    // The temporary validation key is never used by the publication job.
    testBuildType = if (System.getenv("ANIMAN_ANDROID_KEYSTORE").isNullOrBlank()) "validation" else "release"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.webkit:webkit:1.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("dev.ffmpegkit-maintained:ffmpeg-kit-min:6.0.4")
    // The maintained AAR still references these original exception helpers but
    // does not declare them in its published dependency metadata.
    implementation("com.arthenica:smart-exception-java:0.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:rules:1.6.1")
}

chaquopy {
    defaultConfig {
        version = "3.13"
        extractPackages("animan")
        pip {
            options("--timeout", "120", "--find-links", "${rootProject.projectDir}/wheels")
            install("-r", "${rootProject.projectDir}/requirements.txt")
        }
    }
}

val syncPythonSource by tasks.registering(Sync::class) {
    from("${rootProject.projectDir}/..") {
        include("animan/**")
        include("run.py")
        include("android_runtime.py")
        include("frontend/dist/**")
        exclude("**/__pycache__/**")
        exclude("**/.pytest_cache/**")
        exclude("**/*.pyc")
        exclude("animan/Artefacts/**")
        exclude("animan/ressources/**")
    }
    into("${projectDir}/src/main/python")
}

tasks.matching { it.name.contains("Python") && it.name != "syncPythonSource" }.configureEach {
    dependsOn(syncPythonSource)
}
tasks.named("preBuild") {
    dependsOn(syncPythonSource)
}
