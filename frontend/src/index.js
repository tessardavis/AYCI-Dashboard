import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Register the PWA service worker so the dashboard becomes installable
// ("Add to Home Screen") on iOS and Chrome / Edge. The SW does not cache
// application data — it's just a no-op pass-through that satisfies the
// installability criteria.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Silently ignore — installability is nice-to-have, not critical
    });
  });
}
