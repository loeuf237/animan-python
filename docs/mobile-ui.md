# Mobile interface and browser regression checks

The mobile interface uses the same Vue application as the desktop browser and
Android WebView. On narrow screens:

- Download actions move below the content, leaving readable titles, progress,
  verification and export states. Queue priority controls remain available.
- The header, statistics and four status filters are compact. Global commands
  are available through **Actions and settings**; the toolbar scrolls with the
  page instead of covering download cards.
- Protection instructions can be expanded when a download in the current view
  needs verification. Finished downloads do not show other tasks' warnings.
- Export status stays visible; the full destination path is expandable.
- Settings use a section selector; source choices wrap instead of being cut off.
- Source actions use a compact two-column grid. Extension import inputs fit
  their container, including on 320 px screens.
- Speed settings use the shared dialog, outside animated page containers, with
  focus restoration, Escape, a keyboard focus loop and a scrollable height limit.
- Bottom navigation reserves space at the end of the page and respects safe-area
  insets. Download action targets remain at least 44 × 44 CSS pixels.

## Run automated checks

From `frontend/`, using Node 22.12 or newer:

```bash
npm ci
npm test
npx playwright install --with-deps chromium
npm run test:ui
npm run build
```

For locally installed Chrome, browser download can be skipped:

```bash
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/path/to/chrome npm run test:ui
```

The suite starts an isolated Vite server on `127.0.0.1:5179`. All API calls and
external requests are intercepted. It does not use the real database, access
streaming sites, export files or start downloads. Stop another server on that
port before running it, or use another port in both the config and fixtures.

Checks cover 320, 360, 390, 412, 768, 769, 900, 1024 and 1440 px widths, in
French/dark and English/light configurations. They exercise active, queued,
paused, completed, failed, blocked and export-failed tasks; settings sections;
source navigation; imported extension cards; the other main pages; keyboard
search; action API requests; and changing the viewport while a page is open. Short portrait (360 × 640) and
landscape (740 × 360) screens also exercise dialog and search visibility.

They assert document width against the **requested viewport width**: on mobile,
checking only `scrollWidth <= innerWidth` can miss a page that has already been
expanded by overflowing content. Import fields are also checked against their
card bounds, because `overflow: hidden` can conceal a broken layout.

Screenshots at 360, 390 and 1440 px are saved under `artifacts/mobile-ui/`.
`after-*` files capture full pages; `viewport-*` files show the actual visible
screen. Playwright writes an HTML report to `frontend/playwright-report/` and
retains traces/screenshots when a test fails. CI uploads these as
`animelab-ui-validation`. Generated files are ignored by Git.

## Physical-device checklist

Browser emulation verifies web layout and event handling. It does not validate
Android permissions, the system folder picker, hardware video decoding, the
WebView keyboard, or a particular installed APK.

1. Install an APK rebuilt with these frontend changes. An already-installed APK
   bundles its own web assets and does not receive local source changes.
2. On Android 10, open Downloads in portrait and landscape. Try a long series
   title, an unknown file size, a queued task and a completed/exported task.
3. Check pause/resume, queue priority, speed settings, playback and export.
   Expand the destination and an export error, if present.
4. Scroll to the last item: its actions must be reachable above the navigation.
5. Open Settings and visit every section. Choose each source without horizontal
   clipping; save a preference and verify it after reopening the page.
6. Open search, type with the software keyboard, change source, close it and
   return to the previous page. Check large system font settings.
7. Repeat in English and the light theme. On iOS/Safari, check the safe areas and
   the software keyboard separately.

The Android folder picker is a system screen; its appearance is controlled by
Android rather than the web interface.
