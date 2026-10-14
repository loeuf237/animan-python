# Animan 0.1.0 Android beta

Standalone Python 3.13 engine and compiled Vue interface, embedded with Chaquopy
17.1 and displayed in Android System WebView. A remote computer is not required.

- **Android 10+ (API 29), ARM64 only.** 32-bit ARM and native x86 APKs are not provided.
- The shared curl_cffi transport, source adapters, direct/Range transfers, HLS,
  AES-128, subtitle downloads, FFmpeg muxing and ffprobe verification are included.
- FFmpeg runs through JNI. AES uses Android's javax.crypto provider.
- Downloads run under an Android foreground service with a pause notification.
  Partial files and SQLite remain private; verified media is copied into
  `Downloads/Animan` through MediaStore. The private library copy is retained.
- The engine listens only on an authenticated IPv4 loopback port. Source
  verification uses a separate WebView; external browsers cannot transfer their
  private cookies to Animan. Managed verification with a proxy remains unavailable.
- Android's background restrictions still apply. Transfers pause if a foreground
  start is refused or its Android 15 time allowance expires. After process death,
  reopen Animan and resume paused tasks.

Publication requires packaged-engine/16 KB ELF checks and successful emulator
instrumentation on Android 11 and Android 15: ARM64 runtime/UI/API, native imports,
TLS, Activity recreation, Java AES and storage export. Media commands use the
same Kotlin bridge in a separate native x86_64 test application (encode, remux,
subtitle mux, decode and error handling). Direct/HLS resume has shared Python
regression coverage. **The full ARM64 media pipeline has not been tested.**
**Real-phone testing has not been performed.** This is a beta, not a claim of
validated playback/battery behavior on every phone. Playback depends on the
device's WebView and codec support; exported MKV files can be opened with a
compatible Android player.

The signing key differs from the historical debug-signed 2.1.0 APK. Android may
require uninstalling that old APK; uninstalling removes its private data. Export
any needed data first. Future releases retain the dedicated release identity.

Assets include the APK, build provenance and SHA-256 checksums. FFmpeg is the
LGPL variant `dev.ffmpegkit-maintained:ffmpeg-kit-min:6.0.4`; its corresponding
source is available from [the maintained FFmpegKit project](https://github.com/ffmpegkit-maintained/ffmpeg).
