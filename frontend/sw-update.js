/**
 * sw-update.js — PWA Auto-Update Handler
 * Include this in every HTML page:  <script src="./sw-update.js"></script>
 *
 * What it does:
 *  1. Registers the service worker.
 *  2. Listens for the SW_UPDATED message posted by the new service worker.
 *  3. Shows a beautiful "New version available" toast with a Reload button.
 *  4. Also checks for a waiting (already-downloaded) worker on every page load.
 */

(function () {
  "use strict";

  // ── Inject toast styles once ──────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("__sw_update_styles__")) return;
    const style = document.createElement("style");
    style.id = "__sw_update_styles__";
    style.textContent = `
      #sw-update-toast {
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%) translateY(120px);
        z-index: 999999;
        display: flex;
        align-items: center;
        gap: 14px;
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        color: #fff;
        padding: 14px 20px;
        border-radius: 16px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.45);
        font-family: 'Segoe UI', sans-serif;
        font-size: 14px;
        min-width: 280px;
        max-width: 90vw;
        transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
                    opacity  0.4s ease;
        opacity: 0;
      }
      #sw-update-toast.show {
        transform: translateX(-50%) translateY(0);
        opacity: 1;
      }
      #sw-update-toast .sw-toast-icon {
        font-size: 22px;
        flex-shrink: 0;
        animation: sw-spin 1.4s linear infinite;
      }
      @keyframes sw-spin {
        0%   { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
      #sw-update-toast .sw-toast-text {
        flex: 1;
        line-height: 1.4;
      }
      #sw-update-toast .sw-toast-text strong {
        display: block;
        font-size: 15px;
        margin-bottom: 2px;
      }
      #sw-update-toast .sw-toast-text span {
        font-size: 12px;
        opacity: 0.75;
      }
      #sw-update-reload-btn {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: #fff;
        border: none;
        border-radius: 10px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
        transition: transform 0.15s, box-shadow 0.15s;
        flex-shrink: 0;
      }
      #sw-update-reload-btn:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 12px rgba(99,102,241,0.5);
      }
      #sw-update-dismiss-btn {
        background: transparent;
        border: none;
        color: rgba(255,255,255,0.5);
        font-size: 18px;
        cursor: pointer;
        padding: 0 2px;
        line-height: 1;
        flex-shrink: 0;
      }
      #sw-update-dismiss-btn:hover { color: #fff; }
    `;
    document.head.appendChild(style);
  }

  // ── Show the update toast ─────────────────────────────────────────────────
  function showUpdateToast(onReload) {
    injectStyles();

    // Don't show twice
    if (document.getElementById("sw-update-toast")) return;

    const toast = document.createElement("div");
    toast.id = "sw-update-toast";
    toast.innerHTML = `
      <span class="sw-toast-icon">🔄</span>
      <div class="sw-toast-text">
        <strong>Update Available!</strong>
        <span>A new version has been deployed.</span>
      </div>
      <button id="sw-update-reload-btn">Reload</button>
      <button id="sw-update-dismiss-btn" title="Dismiss">✕</button>
    `;
    document.body.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
      requestAnimationFrame(() => toast.classList.add("show"));
    });

    document.getElementById("sw-update-reload-btn").addEventListener("click", () => {
      toast.classList.remove("show");
      setTimeout(onReload, 400);
    });

    document.getElementById("sw-update-dismiss-btn").addEventListener("click", () => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 400);
    });

    // Auto-reload after 15 seconds if user doesn't act
    setTimeout(() => {
      if (document.getElementById("sw-update-toast")) {
        onReload();
      }
    }, 15000);
  }

  // ── Register SW and wire up update detection ──────────────────────────────
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js")
      .then((registration) => {

        // Case 1: A new SW downloaded and waiting — notify immediately
        if (registration.waiting) {
          showUpdateToast(() => window.location.reload());
        }

        // Case 2: New SW starts installing while page is open
        registration.addEventListener("updatefound", () => {
          const newWorker = registration.installing;
          if (!newWorker) return;
          newWorker.addEventListener("statechange", () => {
            // New SW installed and old one still running → show toast
            if (
              newWorker.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              showUpdateToast(() => window.location.reload());
            }
          });
        });

        // Proactively check for updates every 60 seconds (important for mobile
        // which can keep the same tab open for hours)
        setInterval(() => {
          registration.update().catch(() => {});
        }, 60 * 1000);
      })
      .catch((err) => {
        console.warn("[SW] Registration failed:", err);
      });

    // Case 3: New SW activated via postMessage (SW_UPDATED) → reload
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data && event.data.type === "SW_UPDATED") {
        // The new SW already activated, just reload to load fresh assets
        showUpdateToast(() => window.location.reload());
      }
    });

    // Case 4: SW controller changes (new SW took over) → reload
    let refreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });
  });
})();
