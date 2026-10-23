# AnimeLab 0.1.1 — Android beta 1

Android 10+ · ARM64 · package `com.animan.app` · version code **215**.

## Changes since 0.1.0 beta 2

- Compact download screens: readable episode titles and progress, actions below the content, collapsible global controls, and expandable export locations.
- Mobile settings section selector, compact source cards and extension filters that fit narrow screens.
- Safe-area spacing and touch targets, with search and speed-limit dialogs usable in portrait and landscape.
- English/French browser regression coverage from 320 to 1440 pixels, including active, queued, paused, completed, failed and blocked downloads.
- Persistent download preferences across engine restarts. Existing storage/export, playback and native packaging improvements remain included.

## Install or update

Install `AnimeLab-v0.1.1-Android-arm64.apk` over the existing app. Version code 215 is higher than the previous release's 214. The application ID and production signing identity are preserved, so a normal update retains the library, settings and storage grants without an uninstall.

GitHub Actions compiles and signs the APK with the existing identity, validates its certificate and native alignment, runs emulator checks, and publishes only after those gates succeed. The release includes `Android-build-info.json` and `SHA256SUMS.txt` for source provenance and integrity verification.

## Validation limits

Publication requires API **29, 30 and 35** checks. API 29 exercises the shared native media/storage probe. API 30/35 exercise the ARM64 Python/Vue engine through native translation; media/storage probes use the shared JNI implementations built for x86_64.

**This APK has not been tested on a physical phone.** Browser emulation verifies responsive layouts, not the exact behavior of every Android WebView. Complete ARM64 media processing and storage/export checks on a real device remain necessary. External sources may still require manual verification or be unavailable. This Android release remains a **prerelease**.
