# Android distribution and validation

The current target is Android 10+ / ARM64, Python 3.13 and Chaquopy 17.1.0.
`android/requirements.txt` pins the runtime. `scripts/android_native_wheels.py`
builds cffi 2.0.0, pydantic-core 2.41.5 and lxml 6.1.3 with recent libxml2/libxslt
against a pinned Chaquopy toolchain;
curl_cffi 0.16.3 uses its unchanged official ARM64 wheel. Desktop wheels are never
renamed into Android artifacts. AES uses javax.crypto rather than an outdated
Android cryptography/OpenSSL wheel.

`release-android.yml` builds Vue, the shared backend, native media libraries and
instrumentation. Without a production key it builds a **validation APK with a
temporary debug identity** and refuses publication. With the release identity it
tests the signed release APK. Both paths inspect the actual packaged engine and
ELF page alignment and RELRO mapping. Android 11/15 Google APIs x86 guests test
the ARM64 Python/Vue runtime via native translation; a separate test application
executes the **same Kotlin media bridge** using genuine x86_64 FFmpeg libraries.
These are separate checks, not a completed ARM64 download-pipeline test. The
software ARM64 guest probe is retained for diagnosis: current SDK system
services crash during boot in that environment. A physical ARM64 test is needed.

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

Local signing avoids transferring the private identity to GitHub:

```bash
python scripts/android_sign_release.py build/android-candidate build/android-signed \
  --build-tools "$ANDROID_HOME/build-tools/35.0.0"
```

The validation variant inherits release flags and is not debuggable. The script
verifies those flags and input hashes, signs both app and instrumentation with a
dedicated RSA identity, and preserves build provenance. The identity and its
configuration stay in the ignored, private `android/keystore/` directory. Signed
APKs must be tested again before publication. No private key is a release asset.

Release checks cover native imports, Chrome/TLS, SQLite, rendered Vue, loopback
authentication, Activity recreation, Java AES and byte-checked MediaStore export.
The native media probe covers actual encode, TS/MP4 remux, subtitle mux, decode
and failure reporting on x86_64; shared direct/HLS resume logic has Python
regression coverage. Logs and screenshots are Actions artifacts. Metadata must
record both test ABIs and `full_arm64_media_pipeline_tested: false` while this
limitation remains. Real-device power management and playback are not validated.

Media copies in the private library and shared Downloads occupy space twice.
Private partials/cookies/database are excluded from Android backup. Engine state
(including installed extensions and imported proxy lists) uses persistent private
storage rather than the evictable Android cache. No broad
storage permission is requested. Android 15's dataSync time budget and background
start restrictions are handled by pausing the queue, not by bypassing OS policy.

FFmpeg/FFprobe are native JNI libraries, with the LGPL package and corresponding
source link recorded in [the release notes](releases/android-v0.1.0-beta.1.md).
APK checks inspect Python extension libraries inside Chaquopy's nested archives
as well as normal `lib/arm64-v8a` libraries.
Native media commands are serialized; diagnostic collection is bounded before
storage rather than by truncating an already unbounded FFmpegKit session log.
A native worker which fails to stop after cancellation prevents subsequent
commands until the application restarts.
