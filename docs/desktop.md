# Desktop app (Step 18)

Tauri 2 shell around the same React build the web container serves. The
backend stays server-side (FastAPI + Postgres + Redis + Celery) — the
desktop is a native window + API client, not a bundled server.

## What exists and is verified

- `apps/desktop/src-tauri/` (Cargo package `seo-intelligence`,
  `tauri.conf.json`, `build.rs`, `src/main.rs`, store capability).
  `cargo check` and `cargo build` pass; debug binary links.
- Real icon set (`apps/desktop/icons/`, generated from tracked
  `make_icon.py` via `npx tauri icon`): `.ico`, `.icns`, PNG sizes,
  Store logos. `tauri.conf.json` points at them (the old `icons/icon.png`
  reference is gone).
- Corrected `frontendDist: ../../web/dist` (relative to `src-tauri/`);
  `npm run build --workspace apps/web` output verified present.
- Backend endpoint is **not** hardcoded: Settings → Application/Backend URL
  (Test against `/api/v1/health`, Save to localStorage, shared `getBackendUrl`
  in `apps/web/src/lib/api.ts`). Works in the webview as-is; migrating the
  value to the Tauri store plugin (already a dependency + capability) is
  future work — the plugin is wired, the UI still uses localStorage.

## Building installers (maintainer machine)

Prerequisites beyond this repo: NSIS (`makensis`) for `.exe` setup and
WiX v3 (`candle`/`light`) for `.msi` on Windows; standard Xcode tooling for
`.dmg` on macOS. Then:

```powershell
npm run build --workspace apps/web
npx tauri build --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Because C: is typically tight on dev machines, point cargo at roomy disk
before big builds:

```powershell
$env:CARGO_HOME="D:\build-cache\cargo-home"
$env:CARGO_TARGET_DIR="D:\build-cache\target"
```

Bundle targets in `tauri.conf.json` (`msi`, `nsis`, `dmg`, `appimage`,
`deb`) are the goal matrix; CI should build per-OS (no cross-building).
