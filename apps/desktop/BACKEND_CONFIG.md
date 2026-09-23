# Backend URL configuration

The desktop app NEVER hardcodes the API endpoint in source.

Current behavior (implemented, Settings → Application / Backend URL):

1. User enters Backend URL (e.g. `https://api.example.com` or
   `http://localhost:8000`).
2. Test pings `GET {url}/api/v1/health`, shows Connected/Failed.
3. Save persists to localStorage, reused on launch by `getBackendUrl()`
   (see `apps/web/src/lib/api.ts`). Same code path serves web browsers
   and the Tauri webview.

Planned: move the stored value into the Tauri store plugin (dependency
`@tauri-apps/plugin-store` and the `store:allow-*` capability are already
wired in `src-tauri/`) so the endpoint survives cache clears.

Manual test:

1. Launch app → Settings → Backend URL [http://localhost:8000]
2. Test → Connected → Save → use the app
