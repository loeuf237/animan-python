# Android distribution and validation

The [0.1.0 Android beta](https://github.com/loeuf237/animan-python/releases/tag/android-v0.1.0-beta.1)
ships one signed ARM64 APK, build provenance and checksums. It is a standalone
application, not a wrapper requiring a running desktop server. Physical-device
testing and the complete ARM64 media pipeline remain pending.

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
It also tests the real storage/export code on Android 10, 11 and 15; the Android
10 x86 guest cannot execute the full ARM64 engine through native translation.
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

Optional CI signing uses `ANIMAN_ANDROID_KEYSTORE`, `ANIMAN_ANDROID_STORE_PASSWORD`,
`ANIMAN_ANDROID_KEY_PASSWORD` and `ANIMAN_ANDROID_KEY_ALIAS`, with
`ANIMAN_ANDROID_KEYSTORE_BASE64` restored temporarily by the workflow. The beta
uses local signing instead; no private signing material is uploaded to GitHub. The
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

For this beta, `android-assemble-signed.yml` reconstructs the already signed APK
from checksummed transfer chunks and checks its signature and alignment.
`android-signed-validate.yml` reads its Actions artifact with read-only permissions
and tests the signed app and matching instrumentation on API 30 and 35, plus
the native media/storage probe on API 29. Transfer
chunks and instrumentation are removed from the release before publication.

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

## Storage permissions and recovery

Use **Settings → Storage → Android permissions** to check access, authorize a
folder through the system picker, return to `Downloads/Animan`, or change
notification permissions. Downloads remain in private app storage while they
are transferring, merging or being verified. Shared files appear after export.
The MediaStore default requires no broad storage permission on Android 10+.
A chosen folder uses a persistent read/write URI grant rather than an arbitrary
filesystem path; if access is revoked, choose and authorize the folder again.
Android 11+ does not allow selecting the Downloads root in the folder picker;
choose a subfolder or use the MediaStore default.

Completed tasks offer **Export to storage** to retry a failed export or copy the
private download into a newly selected folder. The private copy is retained on
export failure. A subtitle mux failing at the publication stage with `Errno 13`
is handled by reserving a filename and renaming, without Android hard links.
Some Android 11 MediaProvider versions only accept subtitle MIME types in
`Movies/Animan`; Animan falls back there for separate subtitles and displays
that location. A folder authorized through the system picker keeps videos and
subtitles together, independently of MediaStore's MIME/directory restrictions.
