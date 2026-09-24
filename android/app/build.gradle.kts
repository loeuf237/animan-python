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
        minSdk = 24
        targetSdk = 35
        versionCode = 210
        versionName = "2.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        create("release") {
            val debugKey = File(System.getProperty("user.home"), ".android/debug.keystore")
            if (debugKey.exists()) {
                storeFile = debugKey
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
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
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
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
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip {
            options("--timeout", "120")
            install("pydantic<2.0.0")
            install("fastapi<0.100.0")
            install("uvicorn>=0.30.0")
            install("sqlalchemy>=2.0.0")
            install("jinja2>=3.1.4")
            install("aiofiles>=24.1.0")
            install("httpx[socks]>=0.27.0")
            install("socksio>=1.0.0")
            install("beautifulsoup4>=4.12.0")
            install("lxml>=5.2.0")
        }
    }
}

val syncPythonSource by tasks.registering(Sync::class) {
    from("${rootProject.projectDir}/..") {
        include("animan/**")
        include("run.py")
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
