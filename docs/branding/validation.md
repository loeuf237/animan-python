# AnimeLab rename validation — 21 October 2026

The repository was renamed from `loeuf237/animan-python` to `loeuf237/animelab`, retaining GitHub repository ID **1367173465**, history and release assets. The local `origin` URL was updated. The owner chose concept 01, the violet and mint A.

Validation completed before publication:

- **494 Python tests passed**, using a fresh temporary database, downloads and cache; two dependency deprecation warnings remain.
- **29 frontend tests passed** on Node 22.22.1. TypeScript checks and the Vite production build passed. The existing warning about a JavaScript chunk above 500 kB remains.
- Android `:app:processValidationResources` passed offline with cached dependencies: new app label, five density buckets and adaptive launcher resources compile successfully. Android version code advances to **214**.
- Web/static icon copies were checked for identical bytes, correct dimensions and valid image formats. The favicon is served at the URL used by the SPA. The PWA keeps its installation ID and receives a new cache revision.
- All **111 architecture source references** validated; the 17 diagrams and offline gallery were regenerated.
- A separate temporary instance on port 8097 showed the AnimeLab title and selected icon in the rendered interface. It used fresh storage and was stopped after checking; the user's running instance was not restarted.
- New files were checked for private signing identities, application databases and GitHub credentials before staging. Local IDE files, APKs, build output and private signing material remain ignored.

CI now runs on branch pushes, pull requests and manual dispatch. Jobs cover Python 3.12/3.13, frontend tests/build on Node 22, and Android manifest/resource compilation. They use read-only repository permissions and do not need release signing secrets. Release workflows remain separate.

The first GitHub run passed the frontend and Android resource jobs. Its Python jobs exposed assumptions hidden by a warm local checkout: the backend job now downloads the compiled SPA artifact, and the browser integration test waits explicitly for a cold browser to start, retaining startup diagnostics. It continues to use the browser sandbox. A real proxy watcher bug on machines with less than five minutes of uptime was also fixed: the first opted-in health check runs immediately, with the existing five-minute budget for subsequent checks. The regression uses a simulated short uptime. All **54 targeted tests** for these areas passed locally before the follow-up publication.

The freshly renamed Android/Windows/macOS packages have not been built or installed as part of this rename. Resource compilation does not constitute a device test. Previous A11 APK measurements and physical test evidence refer to the earlier, explicitly named artifacts and remain unchanged. Existing package IDs, storage locations and signing identity are intentionally retained for upgrades.
