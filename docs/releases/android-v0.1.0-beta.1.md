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
- **Settings → Storage → Android permissions** displays storage and notification
  access. The Android folder picker can authorize a different folder or an SD
  card with a persistent grant. Revoked access is detected; finished downloads
  can be exported again without downloading the video again. Sidecar subtitles
  are exported when they have not been merged.
- Subtitle publication uses exclusive file reservation and rename on Android;
  filesystems rejecting hard links with `Permission denied` no longer prevent
  an otherwise successful mux from completing. Existing files remain protected.
- The engine listens only on an authenticated IPv4 loopback port. Source
  verification uses a separate WebView; external browsers cannot transfer their
  private cookies to Animan. Managed verification with a proxy remains unavailable.
- Android's background restrictions still apply. Transfers pause if a foreground
  start is refused or its Android 15 time allowance expires. After process death,
  reopen Animan and resume paused tasks.

Publication requires packaged-engine/16 KB ELF checks and successful emulator
instrumentation on Android 11 and Android 15: ARM64 runtime/UI/API, native imports,
TLS, Activity recreation, Java AES, atomic file publication, storage export and
folder-picker cancellation. Android 10, 11 and 15 native storage/media checks use
the same Kotlin implementations in a separate x86_64 test application (encode,
remux, subtitle mux, byte-checked export, paused-export cleanup and error handling).
Android 10's x86 image lacks ARM64 translation; its full-engine check requires
a phone. Direct/HLS resume has shared Python
regression coverage. **The full ARM64 media pipeline has not been tested.**
**The corrected APK has not yet been retested on a physical phone.** This is a beta, not a claim of
validated playback/battery behavior on every phone. Playback depends on the
device's WebView and codec support; exported MKV files can be opened with a
compatible Android player.

The signing key differs from the historical debug-signed 2.1.0 APK. Android may
require uninstalling that old APK; uninstalling removes its private data. Export
any needed data first. Future releases retain the dedicated release identity.

Assets include the APK, build provenance and SHA-256 checksums. FFmpeg is the
LGPL variant `dev.ffmpegkit-maintained:ffmpeg-kit-min:6.0.4`; its corresponding
source is available from [the maintained FFmpegKit project](https://github.com/ffmpegkit-maintained/ffmpeg).
