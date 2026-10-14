# Animan desktop packages

These archives contain the Python engine, the compiled Vue interface, curl_cffi,
yt-dlp and FFmpeg/ffprobe. Python and Node.js are not required on the target machine.
Extract the entire archive: the executable requires its adjacent resources.

- Windows x64: launch `Animan.exe`. The native window uses installed Microsoft
  Edge WebView2; the application can fall back to the installed browser.
- Linux x64: launch `./Animan`. Built on Ubuntu 22.04; requires a compatible glibc
  (2.35 or newer). GTK/WebKit availability varies between distributions; an
  installed browser is the fallback. This is an archive, not a universal AppImage.
- macOS Apple Silicon / Intel: choose the matching archive and open `Animan.app`.
  **UNTESTED ON REAL MAC HARDWARE.** Automated package checks do not certify
  interactive playback or window behavior. The app is not Developer-ID signed
  or notarized; macOS may block opening it. Do not disable system security globally.

The launcher opens `/spa/` on an IPv4 loopback server and pauses active tasks when
closing normally. Data stays in the user's existing Animan directories, outside
the archive. `--headless` starts only the local server; `--self-test` checks the
packaged interface, curl library, temporary SQLite storage and media tools without
contacting anime sources. `--version` reports the application version.

`release-metadata` contains the build commit, dependency versions, media versions
and license notices. The GitHub release supplies `SHA256SUMS.txt` for all assets.
