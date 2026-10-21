# AnimeLab 0.1.0 — Android beta 2

Android 10+ · ARM64 · package `com.animan.app` · version code **214**.

## Changes since beta 1

- **AnimeLab identity:** new name, selected violet/mint A logo, Android launcher icons and updated interface artwork. Content-hashed logo URLs prevent stale browser caches from showing the previous identity.
- **Android storage and exports:** private working files, publication of completed downloads through MediaStore, optional persistent access to a folder or SD card through Android's picker, and independent export retries. Open Settings → Storage to choose and authorize a destination. The compatible default shared destination remains `Downloads/Animan`.
- **Downloads:** separate transfer, media-processing and export stages; bounded native workers; recoverable state across interruption; and corrected HLS assembly with absolute paths on Android.
- **Playback:** improved local playback and persisted progress and track preferences per episode/version.
- **Sources and extensions:** shared source capabilities, extension diagnostics and recipe revision history, and clearer recovery for site protections.
- **Database and support:** versioned migrations, structured errors and a redacted diagnostic export.
- **Smaller packaging:** resource shrinking, preserved Python/JNI bridges, stripped generated native-library copies, removal of unused Android XML dependencies, and duplicate public-asset removal.

## Install or update

Download `AnimeLab-v0.1.0-Android-arm64.apk` and install it over the existing app. The application ID and production signing certificate remain unchanged, so an uninstall is not required. Existing libraries, settings and storage grants are retained by a normal update.

The release contains `SHA256SUMS.txt` and `Android-build-info.json` with its source commit, version code, signature fingerprint, build provenance and test scope. The private signing identity stays on the owner's computer; GitHub receives only signed artifacts.

## Validation scope and limitations

Publication is gated on Android API **29, 30 and 35** checks of the signed candidate. Android 10 x86 emulators exercise the shared native media/storage probe because they cannot run the ARM64 Python engine. API 30/35 exercise the ARM64 runtime through native translation; media/storage probes use the same JNI implementations compiled for x86_64.

**This newly compiled APK has not been tested on a physical phone.** Earlier A11 physical Android 10 results refer to the earlier APK and do not certify this build. Complete ARM64 media-pipeline verification on a real device remains a separate manual check. Site availability, CAPTCHA challenges and unsupported extension-specific logic can still prevent access to individual sources.

This is a **prerelease**, not a stable Android release.
