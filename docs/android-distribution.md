# Android distribution and validation

The current target is Android 10+ / ARM64, Python 3.13 and Chaquopy 17.1.0.
`android/requirements.txt` pins the runtime. `scripts/android_native_wheels.py`
builds cffi 2.0.0 and pydantic-core 2.41.5 against a pinned Chaquopy toolchain;
curl_cffi 0.16.3 uses its unchanged official ARM64 wheel. Desktop wheels are never
renamed into Android artifacts. AES uses javax.crypto rather than an outdated
Android cryptography/OpenSSL wheel.

`release-android.yml` builds Vue, the shared backend, native media libraries and
instrumentation. Without a production key it builds a **validation APK with a
temporary debug identity** and refuses publication. With the release identity it
tests the signed release APK. Both paths inspect the actual packaged engine and
ELF page alignment, then run Android 11/15 Google APIs emulators with ARM native
translation. Translation testing does not replace a physical ARM64 phone test.

Run locally with Python 3.13, JDK 17+, Android SDK 35, NDK and native build tools:

```bash
python3.13 scripts/android_native_wheels.py
cd frontend
npm ci
npm run build
cd ../android
./gradlew assembleValidation assembleValidationAndroidTest
```

The compiled Vue distribution must exist before Gradle synchronizes Python
resources. Test an installed target with:

```bash
python scripts/android_instrumentation.py \
  android/app/build/outputs/apk/validation/app-validation.apk \
  android/app/build/outputs/apk/androidTest/validation/app-validation-androidTest.apk \
  build/android-test-results
```

Release signing uses `ANIMAN_ANDROID_KEYSTORE`, `ANIMAN_ANDROID_STORE_PASSWORD`,
`ANIMAN_ANDROID_KEY_PASSWORD` and `ANIMAN_ANDROID_KEY_ALIAS`. GitHub also needs
`ANIMAN_ANDROID_KEYSTORE_BASE64`, restored temporarily by the workflow. The
`android/keystore/` directory is ignored; never commit or publish its contents.
Preserve a secure backup of the release identity for updates. Publication uses
the separate `android-v0.1.0-beta.1` tag and never modifies desktop `v0.1.0`.

Release gates cover native imports, Chrome/TLS requests, SQLite, packaged Vue,
loopback authentication, Activity recreation, resumed direct media, AES-128 HLS,
subtitle mux and MediaStore export. Logs and a screenshot are saved as Actions
artifacts. A beta may state `physical_device_tested: false`; it must not claim
that real-device power management or all playback codecs were tested.

Media copies in the private library and shared Downloads occupy space twice.
Private partials/cookies/database are excluded from Android backup. No broad
storage permission is requested. Android 15's dataSync time budget and background
start restrictions are handled by pausing the queue, not by bypassing OS policy.

FFmpeg/FFprobe are native JNI libraries, with the LGPL package and corresponding
source link recorded in [the release notes](releases/android-v0.1.0-beta.1.md).
APK checks inspect Python extension libraries inside Chaquopy's nested archives
as well as normal `lib/arm64-v8a` libraries.
