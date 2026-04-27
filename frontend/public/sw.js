// Minimal PWA service worker for AYCI Dashboard.
// We do NOT cache application assets (the dashboard relies on always-fresh
// data from external APIs). The SW exists so the browser shows the
// "Install app" prompt and the user can "Add to Home Screen" cleanly.
//
// Strategy: network-first for everything, with a tiny offline fallback that
// just retries on next request. No cache that might serve stale dashboards.

self.addEventListener("install", (event) => {
  // Activate immediately on first install
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Pass-through fetch handler (required for installability on Chrome / Edge).
self.addEventListener("fetch", (event) => {
  // No-op; let the browser handle the request normally.
});
