import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Django server runs on :8000; Vite forwards API and admin calls to it
// so the browser sees one origin and the session cookie and CSRF token just work.
// For a server build under a sub-path (e.g. https://example.com/Betewubet/), set
// VITE_APP_ROOT=/Betewubet; the built files then load from /Betewubet/static/app/.
const root = (process.env.VITE_APP_ROOT ?? "").replace(/\/+$/, "");

export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? `${root}/static/app/` : "/",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
}));
